"""Dataset upload, status and dashboard routes."""

from __future__ import annotations

import asyncio

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from ...ai.client import AIService
from ...analysis.query import DatasetQuery, QueryError
from ...config import Settings, get_settings
from ...schemas.analysis import AnalysisResult
from ...schemas.api import (
    AskRequest,
    AskResponse,
    ChartDataRequest,
    ChartDataResponse,
    ChartExecuteRequest,
    ChartValidateResponse,
    DashboardResponse,
    DatasetSummary,
    FieldInfo,
    FieldsResponse,
    JobState,
    KPIRefreshResponse,
    PreviewResponse,
    SavedDashboard,
    SavedDashboardSummary,
    SaveDashboardRequest,
    UploadResponse,
)
from ...schemas.dashboard import DashboardSpecification
from ...schemas.enums import JobStatus, SemanticRole, TimeGrain
from ...schemas.profile import DatasetProfile
from ...schemas.quality import DataQualityReport
from ...services import ask as ask_service
from ...services import chart_builder, exporters
from ...services.chart_data import execute_chart
from ...services.pipeline import AnalysisPipeline, JobTracker, PipelineError
from ...services.storage import DatasetNotFound, StorageBackend, StorageError
from ...utils.csvio import CSVParseError, validate_upload
from ...utils.logging import get_logger
from ...utils.serialization import records
from ..deps import (
    DatasetCache,
    get_ai_service,
    get_cache,
    get_pipeline,
    get_storage,
    get_tracker,
    load_query,
    load_specification,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# Read the upload in bounded chunks so a huge file cannot exhaust memory before
# the size check runs.
CHUNK_SIZE = 1024 * 1024


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_dataset(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    storage: StorageBackend = Depends(get_storage),
    tracker: JobTracker = Depends(get_tracker),
    pipeline: AnalysisPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Accept a CSV and start the analysis pipeline in the background."""
    filename = file.filename or "upload.csv"

    content = bytearray()
    while chunk := await file.read(CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File exceeds the {settings.max_upload_bytes // 1_048_576} MB limit."
                ),
            )

    try:
        validate_upload(
            filename,
            len(content),
            max_bytes=settings.max_upload_bytes,
            allowed=settings.allowed_extensions,
        )
    except CSVParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    dataset_id = storage.create_dataset(filename, bytes(content))
    tracker.create(dataset_id, filename)
    tracker.prune()

    background.add_task(_run_pipeline, pipeline, dataset_id, filename)

    return UploadResponse(
        dataset_id=dataset_id,
        filename=filename,
        status=JobStatus.PENDING,
        message="Upload accepted. Analysis has started.",
    )


async def _run_pipeline(
    pipeline: AnalysisPipeline, dataset_id: str, filename: str
) -> None:
    """Background wrapper — the tracker already records failures."""
    try:
        await pipeline.run(dataset_id, filename)
    except (PipelineError, CSVParseError):
        pass
    except Exception:  # pragma: no cover - already logged in the pipeline
        log.exception("Background pipeline crashed for %s", dataset_id)


@router.get("", response_model=list[DatasetSummary])
async def list_datasets(
    storage: StorageBackend = Depends(get_storage),
) -> list[DatasetSummary]:
    summaries: list[DatasetSummary] = []
    for meta in storage.list_datasets():
        try:
            summaries.append(
                DatasetSummary(
                    dataset_id=meta["dataset_id"],
                    name=meta.get("title") or meta.get("filename", "Dataset"),
                    filename=meta.get("filename", "unknown.csv"),
                    n_rows=int(meta.get("n_rows", 0)),
                    n_columns=int(meta.get("n_columns", 0)),
                    domain=meta.get("domain"),
                    created_at=meta["created_at"],
                    status=JobStatus(meta.get("status", "pending")),
                )
            )
        except (KeyError, ValueError):
            continue
    return summaries


@router.get("/{dataset_id}/status", response_model=JobState)
async def get_status(
    dataset_id: str,
    tracker: JobTracker = Depends(get_tracker),
    storage: StorageBackend = Depends(get_storage),
) -> JobState:
    """Poll pipeline progress."""
    state = tracker.get(dataset_id)
    if state is not None:
        return state

    # The job may predate a server restart; reconstruct terminal state from
    # what was persisted so the UI does not hang on a missing job.
    try:
        meta = storage.load_meta(dataset_id)
    except DatasetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    recovered = tracker.create(dataset_id, meta.get("filename", "dataset.csv"))
    if meta.get("status") == "complete":
        for step in recovered.steps:
            step.status = JobStatus.COMPLETE
        tracker.finish(dataset_id)
    elif meta.get("status") == "failed":
        tracker.fail(dataset_id, meta.get("error", "Analysis failed."))
    return tracker.get(dataset_id)  # type: ignore[return-value]


@router.get("/{dataset_id}", response_model=DashboardResponse)
async def get_dashboard(
    dataset_id: str,
    storage: StorageBackend = Depends(get_storage),
    ai: AIService = Depends(get_ai_service),
) -> DashboardResponse:
    """The complete dashboard payload: spec, profile, quality and analysis."""
    specification = load_specification(dataset_id, storage)
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
        quality = storage.load_artifact(dataset_id, "quality", DataQualityReport)
        analysis = storage.load_artifact(dataset_id, "analysis", AnalysisResult)
        meta = storage.load_meta(dataset_id)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return DashboardResponse(
        dataset_id=dataset_id,
        filename=meta.get("filename", "dataset.csv"),
        specification=specification,
        profile=profile,
        quality=quality,
        analysis=analysis,
        ai_enabled=ai.is_enabled,
        created_at=meta["created_at"],
    )


@router.post(
    "/{dataset_id}/charts/{chart_id}/data", response_model=ChartDataResponse
)
async def get_chart_data(
    dataset_id: str,
    chart_id: str,
    request: ChartDataRequest,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> ChartDataResponse:
    """Execute one chart under the caller's filters.

    The chart is resolved from the stored specification by id, so the client
    can only ever run a query the backend already validated.
    """
    specification = load_specification(dataset_id, storage)
    chart = specification.chart(chart_id)
    if chart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chart `{chart_id}` is not part of this dashboard.",
        )

    query = load_query(dataset_id, storage, cache)
    _validate_filters(request.filters, specification, query)

    # An optional per-request grain override lets the time-aggregation control
    # re-bucket a stored chart without persisting a new spec.
    if request.time_grain:
        try:
            chart = chart.model_copy(update={"time_grain": TimeGrain(request.time_grain)})
        except ValueError:
            pass

    return execute_chart(
        chart, query, filters=request.filters, settings=settings
    )


@router.post("/{dataset_id}/charts/execute", response_model=ChartDataResponse)
async def execute_adhoc_chart(
    dataset_id: str,
    request: ChartExecuteRequest,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> ChartDataResponse:
    """Run an ad-hoc chart spec (chart switching, Add Visualization).

    The spec is rebuilt and validated against the real dataset with the same
    rules the recommender uses, so a client cannot execute a chart the engine
    would reject.
    """
    specification = load_specification(dataset_id, storage)
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    query = load_query(dataset_id, storage, cache)
    _validate_filters(request.filters, specification, query)

    try:
        chart = chart_builder.build_and_validate(
            request.chart, profile, settings=settings, available=set(query.columns)
        )
    except chart_builder.ChartBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return execute_chart(chart, query, filters=request.filters, settings=settings)


@router.post("/{dataset_id}/charts/validate", response_model=ChartValidateResponse)
async def validate_adhoc_chart(
    dataset_id: str,
    request: ChartExecuteRequest,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> ChartValidateResponse:
    """Validate a chart spec and report which chart types fit its axes.

    Powers the Add-Visualization live preview and the chart-type menu.
    """
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    query = load_query(dataset_id, storage, cache)
    available = set(query.columns)
    payload = request.chart

    allowed = chart_builder.allowed_types_for(
        x=payload.get("x"),
        y=payload.get("y"),
        profile=profile,
        settings=settings,
        available=available,
    )
    try:
        chart_builder.build_and_validate(
            payload, profile, settings=settings, available=available
        )
        return ChartValidateResponse(ok=True, allowed_types=allowed)
    except chart_builder.ChartBuildError as exc:
        return ChartValidateResponse(ok=False, reason=str(exc), allowed_types=allowed)


@router.post("/{dataset_id}/kpis", response_model=KPIRefreshResponse)
async def refresh_kpis(
    dataset_id: str,
    request: ChartDataRequest,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> KPIRefreshResponse:
    """Recompute KPI values under the caller's filters."""
    from ...kpi.engine import calculate_kpis, discover_kpis

    specification = load_specification(dataset_id, storage)
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    query = load_query(dataset_id, storage, cache)
    _validate_filters(request.filters, specification, query)

    # Recompute using the same definitions that produced the stored KPIs, so a
    # filtered dashboard shows the same metrics with different values.
    definitions = discover_kpis(profile, settings=settings)
    wanted = [k.id for k in specification.kpis]
    ordered = [d for kid in wanted for d in definitions if d.id == kid]
    ordered += [d for d in definitions if d.id not in wanted]

    # Preserve names the model may have improved during generation.
    labels = {k.id: (k.name, k.why_it_matters) for k in specification.kpis}
    for definition in ordered:
        if definition.id in labels:
            definition.name, definition.why_it_matters = labels[definition.id]

    kpis = calculate_kpis(
        ordered,
        query,
        profile,
        filters=request.filters,
        include_comparison=not request.filters,
        limit=len(specification.kpis) or 6,
    )
    return KPIRefreshResponse(
        kpis=[k.model_dump(mode="json") for k in kpis],
        row_count=query.row_count(request.filters),
    )


@router.get("/{dataset_id}/preview", response_model=PreviewResponse)
async def preview_rows(
    dataset_id: str,
    limit: int = 25,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
) -> PreviewResponse:
    """A sample of the cleaned data, for the data quality page."""
    query = load_query(dataset_id, storage, cache)
    limit = max(1, min(limit, 200))
    try:
        frame = query.table(query.columns, limit=limit)
    except QueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return PreviewResponse(
        columns=query.columns,
        rows=records(frame),
        total_rows=query.row_count(),
    )


@router.get("/{dataset_id}/fields", response_model=FieldsResponse)
async def get_fields(
    dataset_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> FieldsResponse:
    """Column metadata for the customization UI (Add Visualization, axes menus)."""
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
    except DatasetNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    from ...utils.formatting import humanize

    fields: list[FieldInfo] = []
    for col in profile.columns:
        is_measure = col.name in profile.measure_columns
        role = col.semantic_role
        suggested = (
            "avg"
            if role in (SemanticRole.PERCENTAGE, SemanticRole.RATIO, SemanticRole.DEMOGRAPHIC)
            else "sum"
            if is_measure
            else "count"
        )
        fields.append(
            FieldInfo(
                name=col.name,
                label=humanize(col.name),
                inferred_type=col.inferred_type.value,
                semantic_role=role.value,
                is_measure=is_measure,
                is_dimension=col.name in profile.dimension_columns
                or col.inferred_type.value in ("categorical", "boolean"),
                is_temporal=col.inferred_type.value == "datetime",
                unique=col.unique,
                missing_pct=col.missing_pct,
                suggested_aggregation=suggested,
            )
        )

    default_grain = None
    if profile.primary_date_column:
        date_col = profile.column(profile.primary_date_column)
        if date_col and date_col.datetime:
            default_grain = date_col.datetime.suggested_grain

    return FieldsResponse(
        fields=fields,
        measures=profile.measure_columns,
        dimensions=[f.name for f in fields if f.is_dimension],
        temporal=profile.datetime_columns,
        primary_date_column=profile.primary_date_column,
        primary_measure_column=profile.primary_measure_column,
        default_time_grain=default_grain,
    )


@router.post("/{dataset_id}/ask", response_model=AskResponse)
async def ask_data(
    dataset_id: str,
    request: AskRequest,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    ai: AIService = Depends(get_ai_service),
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    """Answer a natural-language question about the dataset.

    The number in every answer is computed deterministically before the LLM is
    asked to phrase it — the model never sees the raw rows and never invents a
    figure.
    """
    specification = load_specification(dataset_id, storage)
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    query = load_query(dataset_id, storage, cache)
    _validate_filters(request.filters, specification, query)

    return await ask_service.answer_question(
        request.question,
        profile,
        query,
        ai=ai,
        settings=settings,
        base_filters=request.filters,
    )


_EXPORT_MEDIA = {
    "cleaned-csv": "csv",
    "data-dictionary": "dict",
    "config": "config",
    "semantic-model": "model",
    "report": "report",
    "excel": "excel",
}


@router.get("/{dataset_id}/export/{kind}")
async def export_dataset(
    dataset_id: str,
    kind: str,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
) -> Response:
    """Produce a downloadable export. `kind` is one of the data-level exports."""
    from fastapi.responses import Response as FileResponse

    if kind not in _EXPORT_MEDIA:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown export `{kind}`.",
        )

    specification = load_specification(dataset_id, storage)
    try:
        profile = storage.load_artifact(dataset_id, "profile", DatasetProfile)
        meta = storage.load_meta(dataset_id)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    filename = meta.get("filename", "dataset.csv")
    stem = filename.rsplit(".", 1)[0] or "dataset"

    try:
        if kind == "cleaned-csv":
            frame = storage.load_frame(dataset_id)
            export = exporters.cleaned_csv(frame, stem=stem)
        elif kind == "data-dictionary":
            export = exporters.data_dictionary_csv(profile, stem=stem)
        elif kind == "config":
            export = exporters.dashboard_config_json(
                specification, profile, filename=filename, stem=stem
            )
        elif kind == "semantic-model":
            export = exporters.semantic_model_json(
                profile, specification, filename=filename, stem=stem
            )
        elif kind == "report":
            from ...schemas.analysis import AnalysisResult

            quality = storage.load_artifact(dataset_id, "quality", DataQualityReport)
            analysis = storage.load_artifact(dataset_id, "analysis", AnalysisResult)
            export = exporters.analysis_report_markdown(
                specification, profile, quality, analysis, stem=stem
            )
        else:  # excel
            from ...schemas.analysis import AnalysisResult

            frame = storage.load_frame(dataset_id)
            analysis = storage.load_artifact(dataset_id, "analysis", AnalysisResult)
            export = exporters.excel_workbook(
                frame, specification, profile, analysis, stem=stem
            )
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return FileResponse(
        content=export.content,
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"'
        },
    )


@router.post("/{dataset_id}/dashboards", response_model=SavedDashboard)
async def save_dashboard(
    dataset_id: str,
    request: SaveDashboardRequest,
    storage: StorageBackend = Depends(get_storage),
) -> SavedDashboard:
    """Persist a customized dashboard configuration so it can be reloaded."""
    if not storage.exists(dataset_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset `{dataset_id}` was not found.",
        )
    record = storage.save_dashboard(dataset_id, request.name, request.config)
    return SavedDashboard(**record)


@router.get("/{dataset_id}/dashboards", response_model=list[SavedDashboardSummary])
async def list_dataset_dashboards(
    dataset_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> list[SavedDashboardSummary]:
    """Saved dashboards for one dataset."""
    return [SavedDashboardSummary(**r) for r in storage.list_dashboards(dataset_id)]


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_dataset(
    dataset_id: str,
    storage: StorageBackend = Depends(get_storage),
    cache: DatasetCache = Depends(get_cache),
    tracker: JobTracker = Depends(get_tracker),
) -> Response:
    try:
        storage.delete(dataset_id)
    except DatasetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    # Drop the cached query session and the job record too, otherwise a
    # deleted dataset keeps answering status requests from memory.
    cache.invalidate(dataset_id)
    tracker.remove(dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _validate_filters(
    filters: list, specification: DashboardSpecification, query: DatasetQuery
) -> None:
    """Only columns the dashboard actually exposes as filters are accepted."""
    allowed = {f.column for f in specification.filters}
    for value in filters:
        if value.column not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"`{value.column}` is not a filterable column on this dashboard.",
            )
        if value.column not in query.columns:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown column `{value.column}`.",
            )
