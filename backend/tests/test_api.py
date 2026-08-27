"""API tests against the real pipeline.

These deliberately use the generated sample CSVs and the real FastAPI app:
their purpose is to prove the production path works end to end, including
storage, the background job and the DuckDB query layer.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLES_DIR


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """A client backed by a throwaway storage directory."""
    import app.api.deps as deps
    from app.config import Settings, get_settings

    storage_dir = tmp_path_factory.mktemp("api-storage")
    overrides = Settings(storage_dir=storage_dir, ai_provider="none", ai_api_key="")

    get_settings.cache_clear()
    deps.get_storage.cache_clear()
    deps.get_tracker.cache_clear()
    deps.get_ai_service.cache_clear()
    deps.get_cache.cache_clear()

    from app.main import create_app

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: overrides
    # The storage factory reads settings at construction time, so it has to be
    # rebuilt against the temporary directory.
    from app.services.storage import LocalStorage

    storage = LocalStorage(overrides)
    deps.get_storage.cache_clear()
    application.dependency_overrides[deps.get_storage] = lambda: storage

    with TestClient(application) as test_client:
        yield test_client

    get_settings.cache_clear()


def upload(client: TestClient, name: str) -> str:
    """Upload a sample file and return its dataset id."""
    path = SAMPLES_DIR / name
    with path.open("rb") as handle:
        response = client.post(
            "/api/datasets", files={"file": (name, handle, "text/csv")}
        )
    assert response.status_code == 202, response.text
    return response.json()["dataset_id"]


@pytest.fixture(scope="module")
def sales_dataset(client):
    dataset_id = upload(client, "ecommerce_sales.csv")
    status = client.get(f"/api/datasets/{dataset_id}/status").json()
    assert status["status"] == "complete", status.get("error")
    return dataset_id


class TestSystemRoutes:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_config_never_leaks_the_api_key(self, client):
        body = client.get("/api/config").json()
        assert "ai_enabled" in body
        serialized = str(body).lower()
        assert "api_key" not in serialized
        assert "sk-" not in serialized


class TestUploadValidation:
    def test_rejects_a_non_csv_extension(self, client):
        response = client.post(
            "/api/datasets",
            files={"file": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_rejects_an_empty_file(self, client):
        response = client.post(
            "/api/datasets",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
        )
        assert response.status_code == 400

    def test_missing_file_is_a_validation_error(self, client):
        assert client.post("/api/datasets").status_code == 422

    def test_unparsable_csv_fails_the_job_not_the_request(self, client):
        response = client.post(
            "/api/datasets",
            files={"file": ("bad.csv", io.BytesIO(b"\x00\x01\x02\x03"), "text/csv")},
        )
        assert response.status_code == 202
        dataset_id = response.json()["dataset_id"]
        status = client.get(f"/api/datasets/{dataset_id}/status").json()
        assert status["status"] == "failed"
        assert status["error"]


class TestPipeline:
    def test_status_reports_every_step(self, client, sales_dataset):
        status = client.get(f"/api/datasets/{sales_dataset}/status").json()
        assert status["progress"] == 100.0
        assert all(s["status"] == "complete" for s in status["steps"])
        assert len(status["steps"]) >= 8

    def test_unknown_dataset_returns_404(self, client):
        assert client.get("/api/datasets/deadbeef/status").status_code == 404

    def test_path_traversal_id_is_rejected(self, client):
        response = client.get("/api/datasets/..%2F..%2Fetc/status")
        assert response.status_code in (400, 404)


class TestDashboard:
    def test_returns_a_complete_payload(self, client, sales_dataset):
        body = client.get(f"/api/datasets/{sales_dataset}").json()
        assert body["specification"]["kpis"]
        assert body["specification"]["charts"]
        assert body["specification"]["filters"]
        assert body["specification"]["insights"]
        assert body["profile"]["n_rows"] > 0
        assert body["quality"]["quality_score"] > 0
        assert body["ai_enabled"] is False

    def test_domain_is_detected(self, client, sales_dataset):
        body = client.get(f"/api/datasets/{sales_dataset}").json()
        assert body["specification"]["domain"] == "sales"

    def test_every_kpi_is_grounded(self, client, sales_dataset):
        for kpi in client.get(f"/api/datasets/{sales_dataset}").json()["specification"]["kpis"]:
            assert kpi["value"] is not None
            assert kpi["calculation"]
            assert kpi["why_it_matters"]

    def test_every_insight_cites_evidence(self, client, sales_dataset):
        insights = client.get(
            f"/api/datasets/{sales_dataset}"
        ).json()["specification"]["insights"]
        for insight in insights:
            assert insight["evidence"], insight["title"]


class TestChartData:
    def test_every_chart_returns_rows(self, client, sales_dataset):
        charts = client.get(
            f"/api/datasets/{sales_dataset}"
        ).json()["specification"]["charts"]
        assert charts
        for chart in charts:
            response = client.post(
                f"/api/datasets/{sales_dataset}/charts/{chart['id']}/data",
                json={"filters": []},
            )
            assert response.status_code == 200, chart["id"]
            body = response.json()
            assert body["row_count"] > 0, f"{chart['id']}: {body.get('empty_reason')}"
            assert body["data"]

    def test_unknown_chart_id_returns_404(self, client, sales_dataset):
        response = client.post(
            f"/api/datasets/{sales_dataset}/charts/not_a_chart/data",
            json={"filters": []},
        )
        assert response.status_code == 404

    def test_filters_change_the_data(self, client, sales_dataset):
        spec = client.get(f"/api/datasets/{sales_dataset}").json()["specification"]
        select = next(f for f in spec["filters"] if f["kind"] == "multi_select")
        chart = next(c for c in spec["charts"] if c["type"] == "bar")

        unfiltered = client.post(
            f"/api/datasets/{sales_dataset}/charts/{chart['id']}/data",
            json={"filters": []},
        ).json()
        filtered = client.post(
            f"/api/datasets/{sales_dataset}/charts/{chart['id']}/data",
            json={
                "filters": [
                    {
                        "column": select["column"],
                        "operator": "in",
                        "value": select["options"][:1],
                    }
                ]
            },
        ).json()
        assert filtered["row_count"] <= unfiltered["row_count"]

    def test_filtering_on_a_non_filterable_column_is_rejected(
        self, client, sales_dataset
    ):
        """Only columns the dashboard exposes as filters are accepted."""
        response = client.post(
            f"/api/datasets/{sales_dataset}/kpis",
            json={"filters": [{"column": "revenue", "operator": "gte", "value": 0}]},
        )
        assert response.status_code == 400
        assert "not a filterable column" in response.json()["detail"]

    def test_injection_in_a_filter_column_is_rejected(self, client, sales_dataset):
        response = client.post(
            f"/api/datasets/{sales_dataset}/kpis",
            json={
                "filters": [
                    {
                        "column": "region; DROP TABLE data;--",
                        "operator": "eq",
                        "value": "x",
                    }
                ]
            },
        )
        assert response.status_code == 400


class TestKPIRefresh:
    def test_recomputes_under_filters(self, client, sales_dataset):
        spec = client.get(f"/api/datasets/{sales_dataset}").json()["specification"]
        select = next(f for f in spec["filters"] if f["kind"] == "multi_select")

        everything = client.post(
            f"/api/datasets/{sales_dataset}/kpis", json={"filters": []}
        ).json()
        filtered = client.post(
            f"/api/datasets/{sales_dataset}/kpis",
            json={
                "filters": [
                    {
                        "column": select["column"],
                        "operator": "in",
                        "value": select["options"][:1],
                    }
                ]
            },
        ).json()
        assert filtered["row_count"] < everything["row_count"]
        assert len(filtered["kpis"]) == len(everything["kpis"])
        assert [k["id"] for k in filtered["kpis"]] == [
            k["id"] for k in everything["kpis"]
        ]


class TestPreviewAndDelete:
    def test_preview_returns_cleaned_rows(self, client, sales_dataset):
        body = client.get(f"/api/datasets/{sales_dataset}/preview?limit=5").json()
        assert len(body["rows"]) == 5
        assert body["columns"]
        assert body["total_rows"] > 5

    def test_delete_removes_the_dataset(self, client):
        dataset_id = upload(client, "edge_tiny.csv")
        assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
        assert client.get(f"/api/datasets/{dataset_id}/status").status_code == 404


class TestDatasetVariety:
    """The core promise: different data produces different dashboards."""

    @pytest.mark.parametrize(
        "filename,expected_domain",
        [
            ("hr_employees.csv", "hr"),
            ("marketing_campaigns.csv", "marketing"),
            ("financial_transactions.csv", "finance"),
        ],
    )
    def test_domains_are_recognised(self, client, filename, expected_domain):
        dataset_id = upload(client, filename)
        status = client.get(f"/api/datasets/{dataset_id}/status").json()
        assert status["status"] == "complete", status.get("error")
        spec = client.get(f"/api/datasets/{dataset_id}").json()["specification"]
        assert spec["domain"] == expected_domain

    def test_hr_and_marketing_get_different_kpis(self, client):
        hr_id = upload(client, "hr_employees.csv")
        mk_id = upload(client, "marketing_campaigns.csv")
        hr = client.get(f"/api/datasets/{hr_id}").json()["specification"]
        mk = client.get(f"/api/datasets/{mk_id}").json()["specification"]

        hr_kpis = {k["id"] for k in hr["kpis"]}
        mk_kpis = {k["id"] for k in mk["kpis"]}
        assert hr_kpis != mk_kpis
        assert "attrition_rate" in hr_kpis
        assert "conversion_rate" in mk_kpis

    def test_a_dataset_with_no_dates_still_produces_a_dashboard(self, client):
        dataset_id = upload(client, "edge_categorical_only.csv")
        status = client.get(f"/api/datasets/{dataset_id}/status").json()
        assert status["status"] == "complete"
        spec = client.get(f"/api/datasets/{dataset_id}").json()["specification"]
        assert spec["charts"]
        assert not any(c["type"] in ("line", "area") for c in spec["charts"])

    def test_a_three_row_dataset_does_not_crash(self, client):
        dataset_id = upload(client, "edge_tiny.csv")
        status = client.get(f"/api/datasets/{dataset_id}/status").json()
        assert status["status"] == "complete"
        spec = client.get(f"/api/datasets/{dataset_id}").json()["specification"]
        assert spec["kpis"]
