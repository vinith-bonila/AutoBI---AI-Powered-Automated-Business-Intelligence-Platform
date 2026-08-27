"""AutoBI FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.deps import get_ai_service, get_cache, get_storage
from .api.routes import dashboards, datasets, health
from .config import get_settings
from .services.storage import DatasetNotFound, StorageError
from .utils.csvio import CSVParseError
from .utils.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()

    ai = get_ai_service()
    log.info(
        "%s starting — storage=%s ai=%s",
        settings.app_name,
        settings.storage_backend,
        f"{ai.provider_name}:{ai.model_name}" if ai.is_enabled else "disabled",
    )

    # Clear datasets past the retention window on boot. Uploaded files are
    # temporary by design in the MVP.
    try:
        removed = get_storage().purge_expired(settings.retention_hours)
        if removed:
            log.info("Removed %d expired dataset(s) on startup", removed)
    except StorageError as exc:  # pragma: no cover - non-fatal
        log.warning("Retention sweep failed: %s", exc)

    yield

    get_cache().clear()
    log.info("%s stopped", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="AutoBI API",
        description=(
            "Turn any CSV into an intelligent dashboard. Upload a file, poll "
            "the analysis job, then read the generated dashboard specification "
            "and query its charts."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*" if settings.cors_allow_all else None,
        allow_origins=[] if settings.cors_allow_all else settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(datasets.router)
    app.include_router(dashboards.router)

    # -- error handling ----------------------------------------------------
    # Uploaded data is untrusted, so failures are reported as clean messages
    # rather than stack traces.

    @app.exception_handler(CSVParseError)
    async def _csv_error(request: Request, exc: CSVParseError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "code": "csv_parse_error"},
        )

    @app.exception_handler(DatasetNotFound)
    async def _not_found(request: Request, exc: DatasetNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc), "code": "dataset_not_found"},
        )

    @app.exception_handler(StorageError)
    async def _storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "code": "storage_error"},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # `exc.errors()` can carry a raw exception in each entry's `ctx`, which
        # is not JSON-serialisable — reduce each error to plain strings.
        safe_errors = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())),
                "message": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
            for err in exc.errors()[:5]
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "The request payload was not valid.",
                "code": "validation_error",
                "errors": safe_errors,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Something went wrong while processing the request.",
                "code": "internal_error",
            },
        )

    return app


app = create_app()
