"""Dataset storage.

`StorageBackend` is the seam that keeps the MVP's local-filesystem storage from
leaking into the rest of the codebase. Services depend on this interface, so a
PostgreSQL + object-storage implementation can replace `LocalStorage` without
touching profiling, analysis or the API layer.

Layout on disk (one directory per dataset):

    storage/datasets/<dataset_id>/
        raw.csv          the original upload, byte-for-byte
        clean.parquet    the cleaned, typed frame the dashboard reads
        meta.json        filename, timestamps, status
        profile.json     DatasetProfile
        quality.json     DataQualityReport
        analysis.json    AnalysisResult
        dashboard.json   DashboardSpecification
"""

from __future__ import annotations

import abc
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from ..config import Settings
from ..utils.logging import get_logger

log = get_logger(__name__)

RAW_FILE = "raw.csv"
CLEAN_FILE = "clean.parquet"
META_FILE = "meta.json"

ARTIFACTS = {
    "profile": "profile.json",
    "quality": "quality.json",
    "analysis": "analysis.json",
    "dashboard": "dashboard.json",
}


class StorageError(RuntimeError):
    pass


class DatasetNotFound(StorageError):
    def __init__(self, dataset_id: str):
        super().__init__(f"Dataset `{dataset_id}` was not found.")
        self.dataset_id = dataset_id


class StorageBackend(abc.ABC):
    """Everything the pipeline needs to persist and retrieve a dataset."""

    @abc.abstractmethod
    def create_dataset(self, filename: str, content: bytes) -> str: ...

    @abc.abstractmethod
    def raw_path(self, dataset_id: str) -> Path: ...

    @abc.abstractmethod
    def save_frame(self, dataset_id: str, frame: pd.DataFrame) -> None: ...

    @abc.abstractmethod
    def load_frame(self, dataset_id: str) -> pd.DataFrame: ...

    @abc.abstractmethod
    def save_artifact(self, dataset_id: str, kind: str, model: BaseModel) -> None: ...

    @abc.abstractmethod
    def load_artifact(self, dataset_id: str, kind: str, model: type) -> Any: ...

    @abc.abstractmethod
    def save_meta(self, dataset_id: str, meta: dict) -> None: ...

    @abc.abstractmethod
    def load_meta(self, dataset_id: str) -> dict: ...

    @abc.abstractmethod
    def exists(self, dataset_id: str) -> bool: ...

    @abc.abstractmethod
    def list_datasets(self) -> list[dict]: ...

    @abc.abstractmethod
    def delete(self, dataset_id: str) -> None: ...

    @abc.abstractmethod
    def purge_expired(self, older_than_hours: int) -> int: ...


class LocalStorage(StorageBackend):
    """Filesystem-backed storage for the MVP."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._root = settings.datasets_dir
        self._root.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------

    def _dir(self, dataset_id: str, *, create: bool = False) -> Path:
        safe = _validate_id(dataset_id)
        path = self._root / safe
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            raise DatasetNotFound(dataset_id)
        return path

    def raw_path(self, dataset_id: str) -> Path:
        return self._dir(dataset_id) / RAW_FILE

    # -- lifecycle ---------------------------------------------------------

    def create_dataset(self, filename: str, content: bytes) -> str:
        dataset_id = uuid.uuid4().hex
        directory = self._dir(dataset_id, create=True)
        (directory / RAW_FILE).write_bytes(content)
        self.save_meta(
            dataset_id,
            {
                "dataset_id": dataset_id,
                "filename": filename,
                "size_bytes": len(content),
                "created_at": _now(),
                "status": "pending",
            },
        )
        log.info("Created dataset %s from %s (%d bytes)", dataset_id, filename, len(content))
        return dataset_id

    def exists(self, dataset_id: str) -> bool:
        try:
            return (self._root / _validate_id(dataset_id)).is_dir()
        except StorageError:
            return False

    def delete(self, dataset_id: str) -> None:
        directory = self._dir(dataset_id)
        shutil.rmtree(directory, ignore_errors=True)
        log.info("Deleted dataset %s", dataset_id)

    def purge_expired(self, older_than_hours: int) -> int:
        """Remove datasets past the retention window."""
        if older_than_hours <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        removed = 0
        for directory in self._root.iterdir():
            if not directory.is_dir():
                continue
            try:
                meta = json.loads((directory / META_FILE).read_text("utf-8"))
                created = datetime.fromisoformat(meta["created_at"])
            except (OSError, ValueError, KeyError):
                continue
            if created < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
                removed += 1
        if removed:
            log.info("Purged %d expired dataset(s)", removed)
        return removed

    # -- frames ------------------------------------------------------------

    def save_frame(self, dataset_id: str, frame: pd.DataFrame) -> None:
        directory = self._dir(dataset_id, create=True)
        # Parquet preserves dtypes exactly, so the analysis layer never has to
        # re-infer types that the cleaner already settled.
        frame.to_parquet(directory / CLEAN_FILE, index=False)

    def load_frame(self, dataset_id: str) -> pd.DataFrame:
        path = self._dir(dataset_id) / CLEAN_FILE
        if not path.exists():
            raise StorageError(
                f"Dataset `{dataset_id}` has not finished processing yet."
            )
        return pd.read_parquet(path)

    # -- artifacts ---------------------------------------------------------

    def save_artifact(self, dataset_id: str, kind: str, model: BaseModel) -> None:
        filename = ARTIFACTS.get(kind)
        if filename is None:
            raise StorageError(f"Unknown artifact kind `{kind}`.")
        directory = self._dir(dataset_id, create=True)
        (directory / filename).write_text(
            model.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_artifact(self, dataset_id: str, kind: str, model: type) -> Any:
        filename = ARTIFACTS.get(kind)
        if filename is None:
            raise StorageError(f"Unknown artifact kind `{kind}`.")
        path = self._dir(dataset_id) / filename
        if not path.exists():
            raise StorageError(
                f"`{kind}` is not available for dataset `{dataset_id}` yet."
            )
        return model.model_validate_json(path.read_text(encoding="utf-8"))

    # -- metadata ----------------------------------------------------------

    def save_meta(self, dataset_id: str, meta: dict) -> None:
        directory = self._dir(dataset_id, create=True)
        existing: dict = {}
        path = directory / META_FILE
        if path.exists():
            try:
                existing = json.loads(path.read_text("utf-8"))
            except ValueError:
                existing = {}
        existing.update(meta)
        existing["updated_at"] = _now()
        path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

    def load_meta(self, dataset_id: str) -> dict:
        path = self._dir(dataset_id) / META_FILE
        if not path.exists():
            raise DatasetNotFound(dataset_id)
        try:
            return json.loads(path.read_text("utf-8"))
        except ValueError as exc:
            raise StorageError(f"Metadata for `{dataset_id}` is corrupt.") from exc

    def list_datasets(self) -> list[dict]:
        out: list[dict] = []
        for directory in self._root.iterdir():
            if not directory.is_dir():
                continue
            try:
                out.append(json.loads((directory / META_FILE).read_text("utf-8")))
            except (OSError, ValueError):
                continue
        out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_id(dataset_id: str) -> str:
    """Reject anything that is not a plain hex id.

    Dataset ids arrive from URLs, so this is the boundary that stops a crafted
    id from escaping the storage root via `../`.
    """
    candidate = (dataset_id or "").strip()
    if not candidate or len(candidate) > 64 or not candidate.isalnum():
        raise StorageError(f"Invalid dataset id `{dataset_id}`.")
    return candidate


def build_storage(settings: Settings) -> StorageBackend:
    """Factory so the backend can be swapped from configuration."""
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorage(settings)
    raise StorageError(
        f"Unsupported storage backend `{settings.storage_backend}`. "
        "Only `local` is implemented in this build."
    )
