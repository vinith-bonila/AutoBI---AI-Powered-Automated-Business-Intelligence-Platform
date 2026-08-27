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

    def test_purge_expired_timestamp_offset_is_encoded_not_spaced(self, storage):
        """Regression: the retention sweep sent `created_at=lt.<ts>+00:00` by
        raw concatenation, so the server decoded the `+` as a space and Postgres
        rejected it (22007 invalid timestamp). The filter must go through the
        client's encoding so `+00:00` survives as `%2B00:00`, not ` 00:00`.
        """
        from urllib.parse import parse_qs, urlparse

        store, _ = storage
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json=[])

        store._client = httpx.Client(
            transport=httpx.MockTransport(handler), headers=store._client.headers
        )
        store.purge_expired(24)

        raw_url = captured["url"]
        # On the wire the '+' must be percent-encoded, never a bare '+'.
        assert "%2B" in raw_url
        # Decoded the way the server does it, the offset is intact — not a space.
        created_at = parse_qs(urlparse(raw_url).query)["created_at"][0]
        assert created_at.startswith("lt.")
        assert "+00:00" in created_at
        assert " 00:00" not in created_at


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

    @pytest.mark.parametrize(
        "bad_url",
        [
            "https://autobi-frontend-41lt.onrender.com",  # the frontend URL
            "https://autobi.vercel.app",
            "http://localhost:3000",
            "https://myapp.netlify.app",
        ],
    )
    def test_rejects_wrong_host_at_init(self, bad_url):
        """A non-Supabase host (the classic misconfig) fails fast with a clear
        message rather than a confusing runtime 404."""
        from app.services.storage import StorageError

        with pytest.raises(StorageError, match="not a Supabase project URL"):
            SupabaseStorage(
                Settings(
                    storage_backend="supabase",
                    supabase_url=bad_url,
                    supabase_service_key="service-key",
                )
            )

    def test_self_hosted_custom_domain_is_allowed(self):
        # A custom domain that isn't a known-wrong host must still be accepted.
        store = SupabaseStorage(
            Settings(
                storage_backend="supabase",
                supabase_url="https://supabase.mycompany.internal",
                supabase_service_key="k",
            )
        )
        assert store._host == "supabase.mycompany.internal"


class TestWrongHostDiagnostics:
    """Reproduces the real-world 404: SUPABASE_URL points at a Next.js/Vercel
    host, so the upload POST gets an HTML 404 page instead of a Supabase reply.
    """

    NEXTJS_404 = (
        '<!DOCTYPE html><html lang="en" data-dpl-id="dpl_3UcGM12SswBA7LCst6ve21Y69Mam">'
        '<head><meta charSet="utf-8" data-next-head=""/></head><body>404</body></html>'
    )

    def _storage_pointed_at_html_host(self):
        # Host passes the init guard (looks like a supabase domain) but the
        # server actually returns Next.js HTML — mimics a proxied/wrong project.
        settings = Settings(
            storage_backend="supabase",
            supabase_url="https://wrong-but-plausible.supabase.co",
            supabase_service_key="super-secret-service-key-DO-NOT-LEAK",
        )
        store = SupabaseStorage(settings)

        def handler(request):
            return httpx.Response(
                404,
                text=self.NEXTJS_404,
                headers={"content-type": "text/html; charset=utf-8"},
            )

        store._client = httpx.Client(
            transport=httpx.MockTransport(handler), headers=store._client.headers
        )
        return store

    def test_upload_html_404_gives_clear_config_error(self):
        from app.services.storage import StorageError

        store = self._storage_pointed_at_html_host()
        with pytest.raises(StorageError) as exc:
            store.create_dataset("raw.csv", b"a,b\n1,2\n")
        message = str(exc.value)
        # The message must name the real problem: SUPABASE_URL / wrong host.
        assert "SUPABASE_URL" in message
        assert "HTML page" in message
        # And it must NEVER leak the service key.
        assert "super-secret-service-key-DO-NOT-LEAK" not in message

    def test_download_html_404_is_not_reported_as_dataset_not_found(self):
        from app.services.storage import StorageError

        store = self._storage_pointed_at_html_host()
        # An HTML 404 is a config error, not a genuine "object missing".
        with pytest.raises(StorageError, match="SUPABASE_URL"):
            store.load_frame("deadbeef")
