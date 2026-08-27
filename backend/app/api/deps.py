"""Shared API dependencies and the dataset cache.

Route handlers hold no business logic; they resolve dependencies here and call
into services. The `DatasetCache` keeps recently used frames (and their DuckDB
sessions) in memory so filtering a dashboard does not re-read parquet on every
interaction.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from functools import lru_cache

from fastapi import Depends, HTTPException, status

from ..ai.client import AIService
from ..analysis.query import DatasetQuery
from ..config import Settings, get_settings
from ..schemas.dashboard import DashboardSpecification
from ..services.pipeline import AnalysisPipeline, JobTracker
from ..services.storage import DatasetNotFound, StorageBackend, StorageError, build_storage
from ..utils.logging import get_logger

log = get_logger(__name__)

CACHE_SIZE = 8


class DatasetCache:
    """A small LRU of open `DatasetQuery` sessions."""

    def __init__(self, capacity: int = CACHE_SIZE):
        self._capacity = capacity
        self._entries: OrderedDict[str, DatasetQuery] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, dataset_id: str, storage: StorageBackend) -> DatasetQuery:
        with self._lock:
            existing = self._entries.get(dataset_id)
            if existing is not None:
                self._entries.move_to_end(dataset_id)
                return existing

        # Load outside the lock: reading parquet can take a moment and must not
        # block other datasets' requests.
        frame = storage.load_frame(dataset_id)
        query = DatasetQuery(frame)

        with self._lock:
            if dataset_id in self._entries:
                query.close()
                self._entries.move_to_end(dataset_id)
                return self._entries[dataset_id]
            self._entries[dataset_id] = query
            while len(self._entries) > self._capacity:
                _, evicted = self._entries.popitem(last=False)
                evicted.close()
        return query

    def invalidate(self, dataset_id: str) -> None:
        with self._lock:
            query = self._entries.pop(dataset_id, None)
        if query is not None:
            query.close()

    def clear(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for query in entries:
            query.close()


@lru_cache
def get_storage() -> StorageBackend:
    return build_storage(get_settings())


@lru_cache
def get_tracker() -> JobTracker:
    return JobTracker()


@lru_cache
def get_ai_service() -> AIService:
    settings = get_settings()
    service = AIService(settings)
    if service.is_enabled:
        log.info("AI enabled: provider=%s model=%s", service.provider_name, service.model_name)
    else:
        log.info("AI disabled — running in deterministic mode.")
    return service


@lru_cache
def get_cache() -> DatasetCache:
    return DatasetCache()


def get_pipeline(
    storage: StorageBackend = Depends(get_storage),
    tracker: JobTracker = Depends(get_tracker),
    ai: AIService = Depends(get_ai_service),
    settings: Settings = Depends(get_settings),
) -> AnalysisPipeline:
    return AnalysisPipeline(
        storage=storage, tracker=tracker, ai=ai, settings=settings
    )


def load_specification(
    dataset_id: str, storage: StorageBackend
) -> DashboardSpecification:
    try:
        return storage.load_artifact(dataset_id, "dashboard", DashboardSpecification)
    except DatasetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


def load_query(
    dataset_id: str, storage: StorageBackend, cache: DatasetCache
) -> DatasetQuery:
    try:
        return cache.get(dataset_id, storage)
    except DatasetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
