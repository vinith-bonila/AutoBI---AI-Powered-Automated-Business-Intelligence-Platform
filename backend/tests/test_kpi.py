"""KPI discovery and calculation."""

from __future__ import annotations

import pandas as pd
import pytest

from app.analysis.query import DatasetQuery
from app.kpi.engine import apply_llm_proposals, calculate_kpis, discover_kpis
from app.schemas.api import FilterValue
from app.schemas.dashboard import LLMKPIProposal
from app.schemas.enums import Aggregation, FilterOperator, GenerationSource, ValueFormat
from conftest import make_frame, profile_of


def kpis_for(frame, settings):
    profile = profile_of(frame, settings)
    from app.cleaning.cleaner import clean_dataset

    cleaned = clean_dataset(frame, profile, settings=settings).frame
    clean_profile = profile_of(cleaned, settings)
    query = DatasetQuery(cleaned)
    definitions = discover_kpis(clean_profile, settings=settings)
    return definitions, query, clean_profile


class TestDiscovery:
    def test_sales_dataset_gets_sales_kpis(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        names = {d.id for d in definitions}
        assert "total_revenue" in names
        assert "record_count" in names
        query.close()

    def test_hr_dataset_gets_attrition_not_ad_spend(self, settings):
        frame = make_frame({
            "employee_id": [f"E{i}" for i in range(60)],
            "department": ["Eng", "Sales", "HR"] * 20,
            "annual_salary": [str(50000 + i * 900) for i in range(60)],
            "left_company": (["Yes", "No", "No", "No"] * 15),
        })
        definitions, query, _ = kpis_for(frame, settings)
        names = {d.id for d in definitions}
        assert "attrition_rate" in names
        assert "return_on_ad_spend" not in names
        query.close()

    def test_marketing_dataset_gets_funnel_kpis(self, settings):
        frame = make_frame({
            "campaign_id": [f"C{i}" for i in range(60)],
            "channel": ["Email", "Search", "Social"] * 20,
            "impressions": [str(10000 + i * 100) for i in range(60)],
            "clicks": [str(500 + i * 7) for i in range(60)],
            "conversions": [str(20 + i) for i in range(60)],
            "spend": [f"${100 + i * 5}.00" for i in range(60)],
            "revenue": [f"${1000 + i * 50}.00" for i in range(60)],
        })
        definitions, query, _ = kpis_for(frame, settings)
        names = {d.id for d in definitions}
        assert "conversion_rate" in names
        assert "click_through_rate" in names
        assert "attrition_rate" not in names
        query.close()

    def test_two_domains_produce_different_kpis(self, settings, sales_frame):
        hr = make_frame({
            "employee_id": [f"E{i}" for i in range(40)],
            "annual_salary": [str(60000 + i * 500) for i in range(40)],
            "left_company": ["Yes", "No", "No", "No"] * 10,
        })
        sales_defs, q1, _ = kpis_for(sales_frame, settings)
        hr_defs, q2, _ = kpis_for(hr, settings)
        assert {d.id for d in sales_defs} != {d.id for d in hr_defs}
        q1.close()
        q2.close()

    def test_categorical_only_dataset_gets_a_record_count(self, settings):
        frame = make_frame({"country": ["DE", "FR", "ES"] * 20})
        definitions, query, _ = kpis_for(frame, settings)
        assert [d.id for d in definitions] == ["record_count"]
        query.close()


class TestCalculation:
    def test_values_match_pandas(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        results = calculate_kpis(definitions, query, profile)
        revenue = next(k for k in results if k.id == "total_revenue")
        expected = float(
            pd.to_numeric(
                sales_frame["revenue"].str.replace(r"[$,]", "", regex=True),
                errors="coerce",
            ).drop_duplicates(keep="first").sum()
        )
        # The duplicate ORD-2 row is removed before aggregation.
        assert revenue.value == pytest.approx(expected, rel=0.02)
        query.close()

    def test_ratio_kpi_is_computed_not_guessed(self, settings):
        # Values vary (a constant column is excluded as a measure) but the
        # margin stays exactly 25%, so the expected result is unambiguous.
        frame = make_frame({
            "order_id": [f"O{i}" for i in range(40)],
            "revenue": [str(100 + i * 4) for i in range(40)],
            "profit": [str((100 + i * 4) * 0.25) for i in range(40)],
        })
        definitions, query, profile = kpis_for(frame, settings)
        results = calculate_kpis(definitions, query, profile)
        margin = next(k for k in results if k.id == "profit_margin")
        assert margin.value == pytest.approx(25.0)
        assert margin.format == ValueFormat.PERCENT
        query.close()

    def test_flag_rate_uses_native_booleans(self, settings):
        frame = make_frame({
            "order_id": [f"O{i}" for i in range(40)],
            "returned": (["Yes"] * 10 + ["No"] * 30),
        })
        definitions, query, profile = kpis_for(frame, settings)
        results = calculate_kpis(definitions, query, profile)
        rate = next(k for k in results if k.id == "return_rate")
        assert rate.value == pytest.approx(25.0)
        query.close()

    def test_filters_change_the_values(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        everything = calculate_kpis(definitions, query, profile)
        filtered = calculate_kpis(
            definitions, query, profile,
            filters=[
                FilterValue(
                    column="region", operator=FilterOperator.IN, value=["North"]
                )
            ],
            include_comparison=False,
        )
        total_all = next(k for k in everything if k.id == "record_count").value
        total_north = next(k for k in filtered if k.id == "record_count").value
        assert total_north < total_all
        query.close()

    def test_every_kpi_is_formatted_and_explained(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        for kpi in calculate_kpis(definitions, query, profile):
            assert kpi.formatted_value
            assert kpi.calculation
            assert kpi.why_it_matters
        query.close()

    def test_uncomputable_kpis_are_dropped_not_shown_as_zero(self, settings):
        frame = make_frame({"a": ["x", "y", "z"] * 10})
        definitions, query, profile = kpis_for(frame, settings)
        results = calculate_kpis(definitions, query, profile)
        assert all(k.value is not None for k in results)
        query.close()

    def test_limit_is_respected(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        assert len(calculate_kpis(definitions, query, profile, limit=3)) <= 3
        query.close()


class TestLLMProposals:
    def test_valid_proposal_is_accepted(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        proposals = [
            LLMKPIProposal(
                name="Average Revenue",
                measure_column="revenue",
                aggregation=Aggregation.AVG,
                format=ValueFormat.CURRENCY,
                why_it_matters="Typical order size.",
                priority=80,
            )
        ]
        merged = apply_llm_proposals(definitions, proposals, profile)
        assert any(d.id == "average_revenue" for d in merged)
        query.close()

    def test_hallucinated_column_is_rejected(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        before = len(definitions)
        proposals = [
            LLMKPIProposal(
                name="Total Sprockets",
                measure_column="sprockets_sold",  # does not exist
                aggregation=Aggregation.SUM,
            )
        ]
        merged = apply_llm_proposals(definitions, proposals, profile)
        assert len(merged) == before
        assert not any("sprocket" in d.id for d in merged)
        query.close()

    def test_ratio_with_one_bad_column_is_rejected(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        before = len(definitions)
        proposals = [
            LLMKPIProposal(
                name="Fake Margin",
                numerator_column="revenue",
                denominator_column="imaginary",
                format=ValueFormat.PERCENT,
            )
        ]
        assert len(apply_llm_proposals(definitions, proposals, profile)) == before
        query.close()

    def test_model_can_rename_a_deterministic_kpi(self, settings, sales_frame):
        definitions, query, profile = kpis_for(sales_frame, settings)
        proposals = [
            LLMKPIProposal(
                name="Total Revenue",
                measure_column="revenue",
                aggregation=Aggregation.SUM,
                why_it_matters="Top-line performance.",
                priority=99,
            )
        ]
        merged = apply_llm_proposals(definitions, proposals, profile)
        revenue = next(d for d in merged if d.id == "total_revenue")
        assert revenue.why_it_matters == "Top-line performance."
        assert revenue.source == GenerationSource.HYBRID
        query.close()
