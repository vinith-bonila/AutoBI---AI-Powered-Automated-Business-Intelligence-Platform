"""Supabase-backed storage.

Files (the raw upload and the cleaned Parquet) live in **Supabase Storage**;
dataset metadata, the analysis artifacts, and saved dashboards live in
**Postgres**, reached through PostgREST. This is the production implementation
of `StorageBackend` — swapping `STORAGE_BACKEND=supabase` moves everything off
the local disk without any other part of the app changing, because they all
depend only on the interface.

Only the service-role key is used, server-side; it never reaches the browser.
Access to the two tables should be locked down with row-level security so the
anon key cannot read them (see `supabase/schema.sql`).
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import pandas as pd
from pydantic import BaseModel

from ..config import Settings
from ..utils.logging import get_logger
from .storage import (
    ARTIFACTS,
    DatasetNotFound,
    StorageBackend,
    StorageError,
    _validate_id,
)

log = get_logger(__name__)

DATASETS_TABLE = "datasets"
DASHBOARDS_TABLE = "saved_dashboards"
RAW_OBJECT = "raw.csv"
CLEAN_OBJECT = "clean.parquet"
# The jsonb columns on the datasets row that hold pydantic artifacts.
_ARTIFACT_COLUMNS = set(ARTIFACTS.keys())  # profile, quality, analysis, dashboard

# Hosts that are DEFINITELY not a Supabase project — the common misconfiguration
# is pasting the frontend / Vercel / Render URL into SUPABASE_URL. Self-hosted
# Supabase on a custom domain still passes (we only reject the known-wrong ones).
_WRONG_HOST_SUFFIXES = (".vercel.app", ".onrender.com", ".netlify.app", ".railway.app")
_WRONG_HOSTS = {"localhost", "127.0.0.1"}


def _looks_like_html(response: httpx.Response) -> bool:
    """True when the response is an HTML page rather than a Supabase reply.

    A Vercel/Next.js 404 (what you get when SUPABASE_URL points at the frontend)
    is an HTML document; a genuine Supabase error is JSON.
    """
    if "text/html" in response.headers.get("content-type", "").lower():
        return True
    head = response.text[:80].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


class SupabaseStorage(StorageBackend):
    def __init__(self, settings: Settings):
        if not settings.supabase_configured:
            raise StorageError(
                "storage_backend=supabase requires SUPABASE_URL and "
                "SUPABASE_SERVICE_KEY to be set."
            )
        self._base = settings.supabase_url.rstrip("/")
        self._bucket = settings.supabase_bucket
        self._host = urlparse(self._base).hostname or ""

        # Fail fast on a URL that is clearly not a Supabase project, with a
        # message that names the exact fix — this is the single most common
        # deployment mistake and otherwise surfaces as a confusing HTML 404.
        host = self._host.lower()
        if (
            not self._base.startswith(("http://", "https://"))
            or host in _WRONG_HOSTS
            or host.endswith(_WRONG_HOST_SUFFIXES)
        ):
            raise StorageError(
                "SUPABASE_URL is not a Supabase project URL "
                f"(host: {self._host or 'missing'}). Set it to "
                "https://<project-ref>.supabase.co — not the frontend, Vercel, "
                "Render, or localhost URL."
            )

        key = settings.supabase_service_key
        # `apikey` + bearer is what both Storage and PostgREST expect.
        self._client = httpx.Client(
            timeout=60.0,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        # Safe startup diagnostics — host + bucket only, NEVER the key.
        log.info(
            "SupabaseStorage ready: host=%s bucket=%s", self._host, self._bucket
        )

    # -- low-level helpers -------------------------------------------------

    def _fail(self, action: str, target: str, response: httpx.Response) -> StorageError:
        """Build a StorageError, logging only key-free diagnostics."""
        log.warning(
            "Supabase %s failed: host=%s bucket=%s target=%s status=%s",
            action, self._host, self._bucket, target, response.status_code,
        )
        if _looks_like_html(response):
            return StorageError(
                f"Supabase {action} returned an HTML page ({response.status_code}), "
                "not a Supabase response — SUPABASE_URL is pointing at the wrong "
                f"host (currently `{self._host}`). It must be "
                "https://<project-ref>.supabase.co, not the frontend/Vercel/Render URL."
            )
        # A genuine Supabase error is short JSON — safe to include a snippet.
        return StorageError(
            f"Supabase {action} `{target}` failed ({response.status_code}): "
            f"{response.text[:200]}"
        )

    def _rest(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(
                method, f"{self._base}/rest/v1/{path}", **kwargs
            )
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase request failed: {exc}") from exc
        if response.status_code >= 400:
            raise self._fail("REST " + method, path.split("?")[0], response)
        return response

    def _object_url(self, dataset_id: str, name: str) -> str:
        return f"{self._base}/storage/v1/object/{self._bucket}/{dataset_id}/{name}"

    def _put_object(self, dataset_id: str, name: str, content: bytes, content_type: str) -> None:
        try:
            response = self._client.post(
                self._object_url(dataset_id, name),
                content=content,
                headers={"content-type": content_type, "x-upsert": "true"},
            )
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase upload failed: {exc}") from exc
        if response.status_code >= 400:
            raise self._fail("upload", name, response)

    def _get_object(self, dataset_id: str, name: str) -> bytes:
        try:
            response = self._client.get(self._object_url(dataset_id, name))
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase download failed: {exc}") from exc
        # A JSON 404 from Supabase means the object is genuinely absent. An HTML
        # 404 means the host is wrong — surface that as a config error, not a
        # (misleading) "dataset not found".
        if response.status_code == 404 and not _looks_like_html(response):
            raise DatasetNotFound(dataset_id)
        if response.status_code >= 400:
            raise self._fail("download", name, response)
        return response.content

    def _delete_object(self, dataset_id: str, name: str) -> None:
        try:
            self._client.delete(self._object_url(dataset_id, name))
        except httpx.HTTPError:
            pass  # best-effort; a missing object is fine on delete

    def _row(self, dataset_id: str, *, select: str = "*") -> dict:
        response = self._rest(
            "GET",
            f"{DATASETS_TABLE}?id=eq.{dataset_id}&select={select}",
        )
        rows = response.json()
        if not rows:
            raise DatasetNotFound(dataset_id)
        return rows[0]

    # -- lifecycle ---------------------------------------------------------

    def create_dataset(self, filename: str, content: bytes) -> str:
        dataset_id = uuid.uuid4().hex
        self._put_object(dataset_id, RAW_OBJECT, content, "text/csv")
        now = _now()
        meta = {
            "dataset_id": dataset_id,
            "filename": filename,
            "size_bytes": len(content),
            "created_at": now,
            "status": "pending",
        }
        self._rest(
            "POST",
            DATASETS_TABLE,
            json={
                "id": dataset_id,
                "filename": filename,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
                "meta": meta,
            },
            headers={"Prefer": "return=minimal"},
        )
        log.info("Created Supabase dataset %s from %s", dataset_id, filename)
        return dataset_id

    def read_raw(self, dataset_id: str) -> bytes:
        return self._get_object(_validate_id(dataset_id), RAW_OBJECT)

    def exists(self, dataset_id: str) -> bool:
        try:
            response = self._rest(
                "GET", f"{DATASETS_TABLE}?id=eq.{_validate_id(dataset_id)}&select=id"
            )
        except StorageError:
            return False
        return bool(response.json())

    def delete(self, dataset_id: str) -> None:
        safe = _validate_id(dataset_id)
        self._delete_object(safe, RAW_OBJECT)
        self._delete_object(safe, CLEAN_OBJECT)
        self._rest(
            "DELETE",
            f"{DATASETS_TABLE}?id=eq.{safe}",
            headers={"Prefer": "return=minimal"},
        )
        log.info("Deleted Supabase dataset %s", dataset_id)

    def purge_expired(self, older_than_hours: int) -> int:
        if older_than_hours <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
        response = self._rest(
            "GET", f"{DATASETS_TABLE}?created_at=lt.{cutoff}&select=id"
        )
        rows = response.json()
        for row in rows:
            try:
                self.delete(row["id"])
            except StorageError:
                continue
        if rows:
            log.info("Purged %d expired Supabase dataset(s)", len(rows))
        return len(rows)

    # -- frames ------------------------------------------------------------

    def save_frame(self, dataset_id: str, frame: pd.DataFrame) -> None:
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        self._put_object(
            _validate_id(dataset_id),
            CLEAN_OBJECT,
            buffer.getvalue(),
            "application/octet-stream",
        )

    def load_frame(self, dataset_id: str) -> pd.DataFrame:
        data = self._get_object(_validate_id(dataset_id), CLEAN_OBJECT)
        return pd.read_parquet(io.BytesIO(data))

    # -- artifacts + metadata (jsonb columns) ------------------------------

    def save_artifact(self, dataset_id: str, kind: str, model: BaseModel) -> None:
        if kind not in _ARTIFACT_COLUMNS:
            raise StorageError(f"Unknown artifact kind `{kind}`.")
        self._patch(
            dataset_id,
            {kind: model.model_dump(mode="json"), "updated_at": _now()},
        )

    def load_artifact(self, dataset_id: str, kind: str, model: type) -> Any:
        if kind not in _ARTIFACT_COLUMNS:
            raise StorageError(f"Unknown artifact kind `{kind}`.")
        row = self._row(_validate_id(dataset_id), select=kind)
        payload = row.get(kind)
        if payload is None:
            raise StorageError(
                f"`{kind}` is not available for dataset `{dataset_id}` yet."
            )
        return model.model_validate(payload)

    def save_meta(self, dataset_id: str, meta: dict) -> None:
        safe = _validate_id(dataset_id)
        try:
            row = self._row(safe, select="meta")
            existing = row.get("meta") or {}
        except DatasetNotFound:
            existing = {}
        merged = {**existing, **meta, "updated_at": _now()}
        patch: dict[str, Any] = {"meta": merged, "updated_at": _now()}
        # Mirror the fields the listing query filters/sorts on to columns.
        if "status" in meta:
            patch["status"] = meta["status"]
        if "filename" in meta:
            patch["filename"] = meta["filename"]
        self._patch(safe, patch)

    def load_meta(self, dataset_id: str) -> dict:
        row = self._row(_validate_id(dataset_id), select="meta")
        meta = row.get("meta")
        if not meta:
            raise DatasetNotFound(dataset_id)
        return meta

    def list_datasets(self) -> list[dict]:
        response = self._rest(
            "GET", f"{DATASETS_TABLE}?select=meta&order=created_at.desc"
        )
        return [row["meta"] for row in response.json() if row.get("meta")]

    def _patch(self, dataset_id: str, values: dict) -> None:
        self._rest(
            "PATCH",
            f"{DATASETS_TABLE}?id=eq.{dataset_id}",
            json=values,
            headers={"Prefer": "return=minimal"},
        )

    # -- saved dashboards --------------------------------------------------

    def save_dashboard(self, dataset_id: str, name: str, config: dict) -> dict:
        _validate_id(dataset_id)
        now = _now()
        record = {
            "id": uuid.uuid4().hex,
            "dataset_id": dataset_id,
            "name": name,
            "config": config,
            "created_at": now,
            "updated_at": now,
        }
        self._rest(
            "POST",
            DASHBOARDS_TABLE,
            json=record,
            headers={"Prefer": "return=minimal"},
        )
        return record

    def load_dashboard(self, dashboard_id: str) -> dict:
        safe = _validate_id(dashboard_id)
        response = self._rest(
            "GET", f"{DASHBOARDS_TABLE}?id=eq.{safe}&select=*"
        )
        rows = response.json()
        if not rows:
            raise DatasetNotFound(dashboard_id)
        return rows[0]

    def list_dashboards(self, dataset_id: str | None = None) -> list[dict]:
        query = f"{DASHBOARDS_TABLE}?select=id,dataset_id,name,created_at,updated_at&order=updated_at.desc"
        if dataset_id:
            query += f"&dataset_id=eq.{_validate_id(dataset_id)}"
        return self._rest("GET", query).json()

    def delete_dashboard(self, dashboard_id: str) -> None:
        safe = _validate_id(dashboard_id)
        self._rest(
            "DELETE",
            f"{DASHBOARDS_TABLE}?id=eq.{safe}",
            headers={"Prefer": "return=minimal"},
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
