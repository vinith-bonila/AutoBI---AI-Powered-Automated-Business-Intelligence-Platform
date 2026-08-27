"""Chart recommendation, validation and the dashboard specification schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analysis.eda import run_analysis
from app.analysis.query import DatasetQuery
from app.charts.recommender import apply_llm_chart_proposals, recommend_charts
from app.charts.validator import validate_chart, validate_charts
from app.schemas.dashboard import (
    ChartSpecification,
    DashboardSpecification,
    LLMChartProposal,
)
from app.schemas.enums import Aggregation, ChartType
from conftest import make_frame, profile_of


def spec(**kwargs) -> ChartSpecification:
    base = {
        "id": "c1",
        "type": ChartType.BAR,
        "title": "Test Chart",
        "aggregation": Aggregation.SUM,
    }
    base.update(kwargs)
    return ChartSpecification(**base)


class TestSchemaShapeRules:
    def test_line_chart_needs_x_and_y(self):
        with pytest.raises(ValidationError, match="requires"):
            spec(type=ChartType.LINE, x="date")

    def test_count_chart_does_not_need_y(self):
        chart = spec(type=ChartType.BAR, x="region", aggregation=Aggregation.COUNT)
        assert chart.y is None

    def test_scatter_needs_both_axes(self):
        with pytest.raises(ValidationError):
            spec(type=ChartType.SCATTER, x="a", aggregation=Aggregation.NONE)

    def test_heatmap_needs_two_columns(self):
        with pytest.raises(ValidationError, match="at least 2"):
            spec(type=ChartType.HEATMAP, columns=["only_one"])

    def test_table_needs_columns(self):
        with pytest.raises(ValidationError, match="requires columns"):
            spec(type=ChartType.TABLE)

    def test_scatter_forces_no_aggregation(self):
        chart = spec(type=ChartType.SCATTER, x="a", y="b", aggregation=Aggregation.SUM)
        assert chart.aggregation == Aggregation.NONE

    def test_ids_are_slugified(self):
        assert spec(id="My Chart", x="a", y="b").id == "my_chart"


class TestValidator:
    def test_rejects_unknown_column(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(type=ChartType.BAR, x="nonexistent", y="revenue")
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok
        assert "does not exist" in result.reason

    def test_rejects_line_chart_without_a_date_axis(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(type=ChartType.LINE, x="region", y="revenue")
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok
        assert "date" in result.reason

    def test_accepts_a_valid_time_series(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(type=ChartType.LINE, x="order_date", y="revenue")
        assert validate_chart(chart, profile, settings=settings).ok

    def test_rejects_grouping_by_an_identifier(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(type=ChartType.BAR, x="order_id", y="revenue")
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok

    def test_rejects_a_pie_with_too_many_slices(self, settings):
        frame = make_frame({
            "city": [f"City {i}" for i in range(30)] * 3,
            "value": [str(i) for i in range(90)],
        })
        profile = profile_of(frame, settings)
        chart = spec(type=ChartType.DONUT, x="city", y="value")
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok
        assert "readable" in result.reason

    def test_rejects_a_share_chart_of_averages(self, settings, clean_sales):
        """Averages do not sum to a whole, so they cannot be sliced."""
        _, profile, _ = clean_sales
        chart = spec(
            type=ChartType.DONUT, x="region", y="revenue", aggregation=Aggregation.AVG
        )
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok
        assert "additive" in result.reason

    def test_rejects_a_share_chart_of_negative_values(self, settings):
        frame = make_frame({
            "kind": ["income", "expense", "fees"] * 20,
            "amount": ["100", "-50", "-10"] * 20,
        })
        profile = profile_of(frame, settings)
        chart = spec(type=ChartType.DONUT, x="kind", y="amount")
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok
        assert "negative" in result.reason

    def test_rejects_a_histogram_of_text(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(type=ChartType.HISTOGRAM, x="region", aggregation=Aggregation.COUNT)
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok

    def test_rejects_a_scatter_against_itself(self, settings, clean_sales):
        _, profile, _ = clean_sales
        chart = spec(
            type=ChartType.SCATTER, x="revenue", y="revenue",
            aggregation=Aggregation.NONE,
        )
        result = validate_chart(chart, profile, settings=settings)
        assert not result.ok

    def test_duplicate_charts_are_collapsed(self, settings, clean_sales):
        _, profile, _ = clean_sales
        a = spec(id="a", type=ChartType.BAR, x="region", y="revenue")
        b = spec(id="b", type=ChartType.BAR, x="region", y="revenue")
        kept, notes = validate_charts([a, b], profile, settings=settings)
        assert len(kept) == 1
        assert any("duplicates" in n for n in notes)


class TestRecommender:
    def _charts(self, frame, settings):
        profile = profile_of(frame, settings)
        from app.cleaning.cleaner import clean_dataset

        cleaned = clean_dataset(frame, profile, settings=settings).frame
        clean_profile = profile_of(cleaned, settings)
        with DatasetQuery(cleaned) as query:
            analysis = run_analysis(cleaned, clean_profile, query, settings=settings)
        return recommend_charts(clean_profile, analysis, settings=settings), clean_profile

    def test_time_series_dataset_gets_a_line_chart(self, settings, sales_frame):
        charts, _ = self._charts(sales_frame, settings)
        assert any(c.type == ChartType.LINE for c in charts)

    def test_every_recommended_chart_is_valid(self, settings, sales_frame):
        charts, profile = self._charts(sales_frame, settings)
        for chart in charts:
            assert validate_chart(chart, profile, settings=settings).ok

    def test_dataset_without_dates_gets_no_line_chart(self, settings):
        frame = make_frame({
            "country": ["DE", "FR", "ES"] * 30,
            "value": [str(i) for i in range(90)],
        })
        charts, _ = self._charts(frame, settings)
        assert not any(c.type in (ChartType.LINE, ChartType.AREA) for c in charts)

    def test_categorical_only_dataset_still_gets_charts(self, settings):
        frame = make_frame({
            "country": ["DE", "FR", "ES", "IT"] * 25,
            "tier": ["gold", "silver", "bronze", "gold"] * 25,
        })
        charts, _ = self._charts(frame, settings)
        assert charts
        assert any(c.type == ChartType.BAR for c in charts)

    def test_numeric_only_dataset_gets_a_histogram(self, settings):
        frame = make_frame({
            f"sensor_{i}": [str(j * (i + 1) % 97) for j in range(120)]
            for i in range(4)
        })
        charts, _ = self._charts(frame, settings)
        types = {c.type for c in charts}
        assert ChartType.HISTOGRAM in types or ChartType.HEATMAP in types

    def test_a_detail_table_is_always_kept(self, settings, sales_frame):
        charts, _ = self._charts(sales_frame, settings)
        assert any(c.type == ChartType.TABLE for c in charts)

    def test_different_datasets_get_different_charts(self, settings, sales_frame):
        other = make_frame({
            "employee_id": [f"E{i}" for i in range(60)],
            "department": ["Eng", "Ops", "Sales"] * 20,
            "annual_salary": [str(50000 + i * 700) for i in range(60)],
        })
        sales_charts, _ = self._charts(sales_frame, settings)
        hr_charts, _ = self._charts(other, settings)
        assert {c.title for c in sales_charts} != {c.title for c in hr_charts}

    def test_sections_are_capped(self, settings, sales_frame):
        charts, _ = self._charts(sales_frame, settings)
        assert len([c for c in charts if c.section == "primary"]) <= 4
        assert len([c for c in charts if c.section == "secondary"]) <= 5


class TestLLMChartProposals:
    def test_valid_proposal_is_added(self, settings, clean_sales):
        _, profile, _ = clean_sales
        proposals = [
            LLMChartProposal(
                type=ChartType.BAR, title="Revenue by Product",
                x="product", y="revenue", aggregation=Aggregation.SUM,
            )
        ]
        merged, notes = apply_llm_chart_proposals(
            [], proposals, profile, settings=settings
        )
        assert any(c.title == "Revenue by Product" for c in merged)

    def test_hallucinated_column_is_rejected_with_a_reason(self, settings, clean_sales):
        _, profile, _ = clean_sales
        proposals = [
            LLMChartProposal(
                type=ChartType.BAR, title="Revenue by Warehouse",
                x="warehouse", y="revenue",
            )
        ]
        merged, notes = apply_llm_chart_proposals(
            [], proposals, profile, settings=settings
        )
        assert merged == []
        assert any("warehouse" in n for n in notes)

    def test_nonsensical_chart_is_rejected(self, settings, clean_sales):
        """The model's charts face the same validator as the rules' charts."""
        _, profile, _ = clean_sales
        proposals = [
            LLMChartProposal(
                type=ChartType.LINE, title="Region Over Time",
                x="region", y="revenue",
            )
        ]
        merged, notes = apply_llm_chart_proposals(
            [], proposals, profile, settings=settings
        )
        assert merged == []
        assert notes


class TestDashboardSpecification:
    def test_round_trips_through_json(self, settings, clean_sales):
        _, profile, _ = clean_sales
        original = DashboardSpecification(
            dataset_id="abc",
            title="Test",
            description="A dashboard.",
            domain="sales",
            charts=[spec(type=ChartType.BAR, x="region", y="revenue")],
        )
        restored = DashboardSpecification.model_validate_json(
            original.model_dump_json()
        )
        assert restored.title == "Test"
        assert restored.charts[0].x == "region"

    def test_chart_lookup_by_id(self):
        chart = spec(id="find_me", type=ChartType.BAR, x="region", y="revenue")
        dashboard = DashboardSpecification(
            dataset_id="abc", title="T", description="D", charts=[chart]
        )
        assert dashboard.chart("find_me") is chart
        assert dashboard.chart("missing") is None

    def test_invalid_chart_type_is_rejected(self):
        with pytest.raises(ValidationError):
            ChartSpecification(
                id="x", type="pyramid", title="Nope", x="a", y="b"
            )
