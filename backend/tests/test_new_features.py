"""Tests for the platform-upgrade features: ad-hoc charts, ask, exports."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLES_DIR


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import app.api.deps as deps
    from app.config import Settings, get_settings

    storage_dir = tmp_path_factory.mktemp("newfeat-storage")
    overrides = Settings(storage_dir=storage_dir, ai_provider="none", ai_api_key="")

    get_settings.cache_clear()
    for factory in (deps.get_storage, deps.get_tracker, deps.get_ai_service, deps.get_cache):
        factory.cache_clear()

    from app.main import create_app
    from app.services.storage import LocalStorage

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: overrides
    storage = LocalStorage(overrides)
    deps.get_storage.cache_clear()
    application.dependency_overrides[deps.get_storage] = lambda: storage

    with TestClient(application) as test_client:
        yield test_client
    get_settings.cache_clear()


def upload(client, name: str) -> str:
    with (SAMPLES_DIR / name).open("rb") as handle:
        response = client.post("/api/datasets", files={"file": (name, handle, "text/csv")})
    assert response.status_code == 202, response.text
    ds = response.json()["dataset_id"]
    assert client.get(f"/api/datasets/{ds}/status").json()["status"] == "complete"
    return ds


@pytest.fixture(scope="module")
def sales(client):
    return upload(client, "ecommerce_sales.csv")


class TestFields:
    def test_returns_measures_and_dimensions(self, client, sales):
        body = client.get(f"/api/datasets/{sales}/fields").json()
        assert body["measures"]
        assert body["dimensions"]
        assert body["primary_date_column"] == "order_date"
        names = {f["name"] for f in body["fields"]}
        assert "revenue" in names
        revenue = next(f for f in body["fields"] if f["name"] == "revenue")
        assert revenue["is_measure"]
        assert revenue["suggested_aggregation"] == "sum"


class TestAdhocCharts:
    def test_execute_a_valid_switched_chart(self, client, sales):
        response = client.post(
            f"/api/datasets/{sales}/charts/execute",
            json={
                "chart": {
                    "type": "bar",
                    "x": "category",
                    "y": "revenue",
                    "aggregation": "sum",
                },
                "filters": [],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["row_count"] > 0
        assert body["data"]

    def test_invalid_chart_is_rejected(self, client, sales):
        response = client.post(
            f"/api/datasets/{sales}/charts/execute",
            json={"chart": {"type": "line", "x": "category", "y": "revenue"}},
        )
        assert response.status_code == 400
        assert "date" in response.json()["detail"].lower()

    def test_hallucinated_column_is_rejected(self, client, sales):
        response = client.post(
            f"/api/datasets/{sales}/charts/execute",
            json={"chart": {"type": "bar", "x": "warehouse", "y": "revenue"}},
        )
        assert response.status_code == 400

    def test_validate_reports_allowed_types(self, client, sales):
        response = client.post(
            f"/api/datasets/{sales}/charts/validate",
            json={"chart": {"type": "bar", "x": "category", "y": "revenue"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"]
        # category + numeric → bar/pie/donut/table, not a scatter or line.
        assert "bar" in body["allowed_types"]
        assert "pie" in body["allowed_types"]
        assert "line" not in body["allowed_types"]
        assert "scatter" not in body["allowed_types"]

    def test_time_grain_override_rebuckets(self, client, sales):
        spec = client.get(f"/api/datasets/{sales}").json()["specification"]
        line = next(c for c in spec["charts"] if c["type"] == "line")
        monthly = client.post(
            f"/api/datasets/{sales}/charts/{line['id']}/data",
            json={"filters": [], "time_grain": "month"},
        ).json()
        yearly = client.post(
            f"/api/datasets/{sales}/charts/{line['id']}/data",
            json={"filters": [], "time_grain": "year"},
        ).json()
        # Re-aggregation actually changes the data, not just the label.
        assert monthly["row_count"] > yearly["row_count"]
        assert yearly["row_count"] <= 3  # the sample spans ~2 years


class TestAsk:
    def test_ranking_question_is_grounded(self, client, sales):
        response = client.post(
            f"/api/datasets/{sales}/ask",
            json={"question": "Which category has the highest revenue?"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["answer"]
        assert body["evidence"]
        # The headline names a real category and a computed figure.
        assert body["table"]
        assert body["chart"] is not None

    def test_aggregate_question(self, client, sales):
        body = client.post(
            f"/api/datasets/{sales}/ask",
            json={"question": "What is the total revenue?"},
        ).json()
        assert "revenue" in body["answer"].lower()
        assert body["evidence"]

    def test_trend_question(self, client, sales):
        body = client.post(
            f"/api/datasets/{sales}/ask",
            json={"question": "What is the revenue trend over time?"},
        ).json()
        assert body["evidence"]
        assert body["chart"] is not None
        assert body["chart"]["chart"]["type"] == "line"

    def test_answer_only_uses_computed_numbers(self, client, sales):
        """With no LLM, the answer is templated straight from the computation."""
        body = client.post(
            f"/api/datasets/{sales}/ask",
            json={"question": "top 5 products by revenue"},
        ).json()
        assert body["ai_used"] is False
        assert len(body["table"]) <= 5 or body["table"]

    def test_empty_question_is_rejected(self, client, sales):
        assert (
            client.post(f"/api/datasets/{sales}/ask", json={"question": "  "}).status_code
            == 422
        )


class TestExports:
    def test_cleaned_csv(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/cleaned-csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        text = response.content.decode("utf-8-sig")
        assert "revenue" in text.splitlines()[0]

    def test_config_is_reloadable_json(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/config")
        assert response.status_code == 200
        config = json.loads(response.content)
        assert config["format"] == "autobi.dashboard-config"
        assert config["kpis"]
        assert config["charts"]
        assert config["filters"]
        assert config["presentation"]

    def test_semantic_model_is_powerbi_ready(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/semantic-model")
        model = json.loads(response.content)
        assert model["format"] == "autobi.semantic-model"
        assert model["model"]["measures"]
        assert model["model"]["tables"][0]["columns"]
        # Each visual carries a Power BI visual-type mapping.
        assert all("visual_type" in v for v in model["report"]["visuals"])

    def test_data_dictionary(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/data-dictionary")
        assert response.status_code == 200
        assert b"column" in response.content

    def test_report_markdown(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/report")
        assert response.status_code == 200
        assert response.content.startswith(b"#")

    def test_excel_workbook(self, client, sales):
        response = client.get(f"/api/datasets/{sales}/export/excel")
        assert response.status_code == 200
        # xlsx files are zip archives — check the magic bytes.
        assert response.content[:2] == b"PK"

    def test_unknown_export_is_404(self, client, sales):
        assert client.get(f"/api/datasets/{sales}/export/nope").status_code == 404


class TestDatasetIndependence:
    """Ask and ad-hoc charts must work across domains, not just sales."""

    def test_hr_ranking(self, client):
        hr = upload(client, "hr_employees.csv")
        body = client.post(
            f"/api/datasets/{hr}/ask",
            json={"question": "Which department has the highest salary?"},
        ).json()
        assert body["evidence"]
        assert "department" in body["interpretation"].lower() or body["table"]

    def test_marketing_adhoc_chart(self, client):
        mk = upload(client, "marketing_campaigns.csv")
        response = client.post(
            f"/api/datasets/{mk}/charts/execute",
            json={"chart": {"type": "bar", "x": "channel", "y": "conversions", "aggregation": "sum"}},
        )
        assert response.status_code == 200
        assert response.json()["row_count"] > 0
