"""SupabaseStorage tests against an in-memory emulator of Storage + PostgREST.

No live Supabase project is needed: an `httpx.MockTransport` stands in for the
REST and Storage endpoints and emulates exactly the request shapes the backend
produces (eq filters, select projection, order, lt, upsert). This verifies the
backend's logic — URL building, jsonb round-tripping, merge-on-save, the full
dataset lifecycle and saved-dashboard CRUD.
"""

from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pandas as pd
import pytest

from app.config import Settings
from app.schemas.profile import DatasetProfile
from app.services.storage import DatasetNotFound
from app.services.supabase_storage import SupabaseStorage


class FakeSupabase:
    """A tiny in-memory stand-in for Supabase Storage + PostgREST."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.tables: dict[str, list[dict]] = {"datasets": [], "saved_dashboards": []}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/storage/v1/object/" in path:
            return self._storage(request)
        if "/rest/v1/" in path:
            return self._rest(request)
        return httpx.Response(404)

    # -- storage -----------------------------------------------------------

    def _storage(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/storage/v1/object/", 1)[1]
        if request.method == "POST":
            self.objects[key] = request.content
            return httpx.Response(200, json={"Key": key})
        if request.method == "GET":
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(200, content=self.objects[key])
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(200)
        return httpx.Response(405)

    # -- postgrest ---------------------------------------------------------

    def _rest(self, request: httpx.Request) -> httpx.Response:
        table = request.url.path.split("/rest/v1/", 1)[1]
        params = parse_qs(urlparse(str(request.url)).query)
        rows = self.tables.setdefault(table, [])

        if request.method == "POST":
            body = json.loads(request.content)
            items = body if isinstance(body, list) else [body]
            rows.extend(items)
            return httpx.Response(201, json=items)

        # Apply eq / lt filters used by the backend.
        def matches(row: dict) -> bool:
            for field, values in params.items():
                if field in ("select", "order"):
                    continue
                spec = values[0]
                if spec.startswith("eq."):
                    if str(row.get(field)) != spec[3:]:
                        return False
                elif spec.startswith("lt."):
                    if not (str(row.get(field)) < spec[3:]):
                        return False
            return True

        selected = [r for r in rows if matches(r)]

        if request.method == "GET":
            select = params.get("select", ["*"])[0]
            if select != "*":
                cols = select.split(",")
                selected = [{c: r.get(c) for c in cols} for r in selected]
            return httpx.Response(200, json=selected)

        if request.method == "PATCH":
            body = json.loads(request.content)
            for r in rows:
                if matches(r):
                    r.update(body)
            return httpx.Response(200, json=[])

        if request.method == "DELETE":
            self.tables[table] = [r for r in rows if not matches(r)]
            return httpx.Response(200, json=[])

        return httpx.Response(405)


@pytest.fixture
def storage():
    fake = FakeSupabase()
    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://demo.supabase.co",
        supabase_service_key="service-key",
    )
    store = SupabaseStorage(settings)
    # Swap the real client for one backed by the emulator.
    store._client = httpx.Client(
        transport=httpx.MockTransport(fake.handler),
        headers=store._client.headers,
    )
    return store, fake


class TestLifecycle:
    def test_create_and_read_raw(self, storage):
        store, _ = storage
        ds = store.create_dataset("sales.csv", b"a,b\n1,2\n")
        assert store.read_raw(ds) == b"a,b\n1,2\n"
        assert store.exists(ds)

    def test_meta_round_trip_and_merge(self, storage):
        store, _ = storage
        ds = store.create_dataset("sales.csv", b"x")
        store.save_meta(ds, {"status": "complete", "n_rows": 100})
        meta = store.load_meta(ds)
        assert meta["status"] == "complete"
        assert meta["n_rows"] == 100
        # Original fields from create_dataset survive the merge.
        assert meta["filename"] == "sales.csv"

    def test_frame_round_trip(self, storage):
        store, _ = storage
        ds = store.create_dataset("d.csv", b"x")
        frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        store.save_frame(ds, frame)
        loaded = store.load_frame(ds)
        pd.testing.assert_frame_equal(loaded, frame)

    def test_artifact_round_trip(self, storage):
        store, _ = storage
        ds = store.create_dataset("d.csv", b"x")
        profile = DatasetProfile(
            dataset_id=ds, name="d.csv", n_rows=3, n_columns=2,
            n_duplicate_rows=0, memory_bytes=100, columns=[],
        )
        store.save_artifact(ds, "profile", profile)
        loaded = store.load_artifact(ds, "profile", DatasetProfile)
        assert loaded.n_rows == 3
        assert loaded.dataset_id == ds

    def test_missing_artifact_raises(self, storage):
        store, _ = storage
        ds = store.create_dataset("d.csv", b"x")
        from app.services.storage import StorageError

        with pytest.raises(StorageError):
            store.load_artifact(ds, "analysis", DatasetProfile)

    def test_list_datasets(self, storage):
        store, _ = storage
        store.create_dataset("a.csv", b"x")
        store.create_dataset("b.csv", b"y")
        listed = store.list_datasets()
        assert len(listed) == 2
        assert {m["filename"] for m in listed} == {"a.csv", "b.csv"}

    def test_delete_removes_files_and_row(self, storage):
        store, fake = storage
        ds = store.create_dataset("d.csv", b"x")
        store.save_frame(ds, pd.DataFrame({"a": [1]}))
        assert len(fake.objects) == 2  # raw + parquet
        store.delete(ds)
        assert not store.exists(ds)
        assert len(fake.objects) == 0

    def test_read_raw_missing_is_not_found(self, storage):
        store, _ = storage
        with pytest.raises(DatasetNotFound):
            store.read_raw("deadbeef")

    def test_purge_expired(self, storage):
        store, fake = storage
        ds = store.create_dataset("old.csv", b"x")
        # Backdate the row so the purge cutoff catches it.
        fake.tables["datasets"][0]["created_at"] = "2000-01-01T00:00:00+00:00"
        removed = store.purge_expired(24)
        assert removed == 1
        assert not store.exists(ds)


class TestSavedDashboards:
    def test_save_and_load(self, storage):
        store, _ = storage
        ds = store.create_dataset("d.csv", b"x")
        record = store.save_dashboard(ds, "My View", {"theme": {"mode": "dark"}})
        loaded = store.load_dashboard(record["id"])
        assert loaded["name"] == "My View"
        assert loaded["config"]["theme"]["mode"] == "dark"
        assert loaded["dataset_id"] == ds

    def test_list_scoped_to_dataset(self, storage):
        store, _ = storage
        a = store.create_dataset("a.csv", b"x")
        b = store.create_dataset("b.csv", b"y")
        store.save_dashboard(a, "A1", {})
        store.save_dashboard(a, "A2", {})
        store.save_dashboard(b, "B1", {})
        assert len(store.list_dashboards(a)) == 2
        assert len(store.list_dashboards(b)) == 1
        assert len(store.list_dashboards()) == 3

    def test_delete(self, storage):
        store, _ = storage
        ds = store.create_dataset("d.csv", b"x")
        record = store.save_dashboard(ds, "X", {})
        store.delete_dashboard(record["id"])
        with pytest.raises(DatasetNotFound):
            store.load_dashboard(record["id"])


class TestConfigGuard:
    def test_requires_credentials(self):
        from app.services.storage import StorageError

        with pytest.raises(StorageError):
            SupabaseStorage(Settings(storage_backend="supabase"))
