"""Saved-dashboard routes (load / delete / list-all).

Save and per-dataset listing live on the datasets router (they have the dataset
in context); these top-level routes load or remove a saved dashboard by its own
id, and list every saved dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...schemas.api import SavedDashboard, SavedDashboardSummary
from ...services.storage import DatasetNotFound, StorageBackend, StorageError
from ..deps import get_storage

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


@router.get("", response_model=list[SavedDashboardSummary])
async def list_all_dashboards(
    storage: StorageBackend = Depends(get_storage),
) -> list[SavedDashboardSummary]:
    return [SavedDashboardSummary(**r) for r in storage.list_dashboards()]


@router.get("/{dashboard_id}", response_model=SavedDashboard)
async def load_dashboard(
    dashboard_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> SavedDashboard:
    try:
        record = storage.load_dashboard(dashboard_id)
    except DatasetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved dashboard `{dashboard_id}` was not found.",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return SavedDashboard(**record)


@router.delete(
    "/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_dashboard(
    dashboard_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    storage.delete_dashboard(dashboard_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
