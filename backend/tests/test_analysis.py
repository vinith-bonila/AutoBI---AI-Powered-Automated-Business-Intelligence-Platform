"""Query layer (including its security properties) and the EDA engine."""

from __future__ import annotations

import pandas as pd
import pytest

from app.analysis.eda import (
    analyze_correlations,
    analyze_segment,
    analyze_trend,
    rank_measures,
    run_analysis,
)
from app.analysis.query import DatasetQuery, QueryError, quote_ident
from app.schemas.api import FilterValue
from app.schemas.enums import Aggregation, FilterOperator, TimeGrain
from conftest import make_frame, profile_of


class TestQuerySafety:
    def test_unknown_column_is_rejected(self, sales_query):
        with pytest.raises(QueryError, match="Unknown column"):
            sales_query.ident("does_not_exist")

    def test_injection_attempt_in_column_name_is_rejected(self, sales_query):
        with pytest.raises(QueryError):
            sales_query.aggregate_by_dimension(
                "region; DROP TABLE data;--", "revenue", Aggregation.SUM
            )

    def test_filter_on_unknown_column_is_rejected(self, sales_query):
        bad = [FilterValue(column="evil", operator=FilterOperator.EQUALS, value="x")]
        with pytest.raises(QueryError):
            sales_query.row_count(bad)

    def test_filter_values_are_bound_not_interpolated(self, sales_query):
        """A quote-laden value must be data, never SQL."""
        hostile = [
            FilterValue(
                column="region",
                operator=FilterOperator.EQUALS,
                value="North' OR '1'='1",
            )
        ]
        assert sales_query.row_count(hostile) == 0

    def test_quote_ident_escapes_embedded_quotes(self):
        assert quote_ident('we"ird') == '"we""ird"'

    def test_column_with_quotes_in_name_still_works(self):
        frame = pd.DataFrame({'we"ird': [1, 2, 3], "n": [4, 5, 6]})
        with DatasetQuery(frame) as query:
            assert query.row_count() == 3
            result = query.aggregate_by_dimension('we"ird', "n", Aggregation.SUM)
            assert len(result) == 3

    def test_aggregation_needs_a_measure(self, sales_query):
        with pytest.raises(QueryError, match="needs a measure"):
            sales_query.scalar(None, Aggregation.SUM)


class TestQueryBuilders:
    def test_row_count(self, sales_query):
        assert sales_query.row_count() == 12

    def test_scalar_sum(self, sales_query, clean_sales):
        frame, _, _ = clean_sales
        expected = float(frame["revenue"].sum())
        assert sales_query.scalar("revenue", Aggregation.SUM) == pytest.approx(expected)

    def test_group_by_excludes_nulls(self, sales_query):
        result = sales_query.aggregate_by_dimension(
            "region", "revenue", Aggregation.SUM
        )
        assert result["label"].notna().all()

    def test_filters_reduce_the_result(self, sales_query):
        unfiltered = sales_query.row_count()
        filters = [
            FilterValue(
                column="region", operator=FilterOperator.IN, value=["North"]
            )
        ]
        assert 0 < sales_query.row_count(filters) < unfiltered

    def test_between_filter_on_dates(self, sales_query):
        filters = [
            FilterValue(
                column="order_date",
                operator=FilterOperator.BETWEEN,
                value=["2024-01-01T00:00:00", "2024-03-31T23:59:59"],
            )
        ]
        assert 0 < sales_query.row_count(filters) < 12

    def test_time_series_grouping(self, sales_query):
        result = sales_query.time_series(
            "order_date", "revenue", Aggregation.SUM, TimeGrain.MONTH
        )
        assert len(result) == 6
        assert "row_count" in result.columns

    def test_time_series_requires_a_date_column(self, sales_query):
        with pytest.raises(QueryError, match="not a date column"):
            sales_query.time_series(
                "region", "revenue", Aggregation.SUM, TimeGrain.MONTH
            )

    def test_histogram_bins_cover_every_row(self, sales_query, clean_sales):
        frame, _, _ = clean_sales
        result = sales_query.histogram("revenue", bins=5)
        assert result["count"].sum() == int(frame["revenue"].notna().sum())

    def test_histogram_rejects_non_numeric(self, sales_query):
        with pytest.raises(QueryError, match="not numeric"):
            sales_query.histogram("region")

    def test_correlation_matrix_is_square(self, sales_query):
        result = sales_query.correlation_matrix(["revenue", "quantity"])
        assert len(result) == 4
        self_corr = result[result["x"] == result["y"]]["value"]
        assert all(v == pytest.approx(1.0) for v in self_corr)

    def test_boolean_conditional_count(self, sales_query):
        """Booleans render as `true` in SQL, never Python's `True`."""
        assert sales_query.conditional_count("returned", True) == 3

    def test_distinct_values(self, sales_query):
        values = sales_query.distinct_values("region")
        assert "North" in values

    def test_table_projection(self, sales_query):
        result = sales_query.table(["region", "revenue"], limit=5)
        assert list(result.columns) == ["region", "revenue"]
        assert len(result) == 5


class TestTrends:
    def test_detects_an_upward_trend(self, settings):
        frame = make_frame({
            "d": pd.date_range("2023-01-01", periods=24, freq="MS").astype(str).tolist(),
            "v": [str(100 + i * 25) for i in range(24)],
        })
        profile = profile_of(frame, settings)
        with DatasetQuery(_typed(frame, profile)) as query:
            trend = analyze_trend(
                query, date_column="d", measure="v",
                aggregation=Aggregation.SUM, grain=TimeGrain.MONTH,
            )
        assert trend is not None
        assert trend.direction == "up"
        assert trend.change_pct > 0
        assert trend.r_squared > 0.9

    def test_excludes_a_partial_final_period(self, settings):
        """Regression: a stub final month read as a catastrophic decline."""
        dates = (
            pd.date_range("2024-01-01", periods=90, freq="D").astype(str).tolist()
            + ["2024-04-01"]  # a single row standing in for all of April
        )
        frame = make_frame({"d": dates, "v": ["100"] * len(dates)})
        profile = profile_of(frame, settings)
        with DatasetQuery(_typed(frame, profile)) as query:
            trend = analyze_trend(
                query, date_column="d", measure="v",
                aggregation=Aggregation.SUM, grain=TimeGrain.MONTH,
            )
        assert trend is not None
        assert trend.partial_period_excluded == "2024-04"
        assert trend.direction == "flat"

    def test_too_few_periods_yields_no_trend(self, settings):
        frame = make_frame({
            "d": ["2024-01-01", "2024-01-02"],
            "v": ["10", "20"],
        })
        profile = profile_of(frame, settings)
        with DatasetQuery(_typed(frame, profile)) as query:
            trend = analyze_trend(
                query, date_column="d", measure="v",
                aggregation=Aggregation.SUM, grain=TimeGrain.MONTH,
            )
        assert trend is None


class TestSegments:
    def test_shares_sum_to_about_one_hundred(self, sales_query):
        segment = analyze_segment(
            sales_query, dimension="region", measure="revenue",
            aggregation=Aggregation.SUM, top_n=10,
        )
        assert segment is not None
        assert sum(r.share_pct for r in segment.top) == pytest.approx(100.0, abs=0.5)

    def test_signed_measures_use_absolute_totals(self):
        """Regression: a mixed-sign ledger produced shares above 100%."""
        frame = pd.DataFrame({
            "category": ["income", "expense", "fees", "other"] * 10,
            "amount": [1000.0, -900.0, -50.0, 20.0] * 10,
        })
        with DatasetQuery(frame) as query:
            segment = analyze_segment(
                query, dimension="category", measure="amount",
                aggregation=Aggregation.SUM,
            )
        assert segment is not None
        assert segment.has_negative_values
        assert segment.share_basis == "absolute_total"
        assert all(0 <= r.share_pct <= 100 for r in segment.top)


class TestCorrelations:
    def test_finds_a_strong_relationship(self, settings):
        frame = make_frame({
            "a": [str(i) for i in range(40)],
            "b": [str(i * 2 + 1) for i in range(40)],
        })
        profile = profile_of(frame, settings)
        pairs = analyze_correlations(_typed(frame, profile), profile)
        assert pairs
        assert pairs[0].coefficient == pytest.approx(1.0, abs=0.01)
        assert pairs[0].strength == "strong"

    def test_ignores_weak_relationships(self, settings):
        frame = make_frame({
            "a": [str(i) for i in range(40)],
            "b": [str((i * 7919) % 41) for i in range(40)],
        })
        profile = profile_of(frame, settings)
        pairs = analyze_correlations(_typed(frame, profile), profile)
        assert all(abs(p.coefficient) >= 0.4 for p in pairs)


class TestRunAnalysis:
    def test_full_analysis_on_sales(self, clean_sales, sales_query, settings):
        frame, profile, _ = clean_sales
        result = run_analysis(frame, profile, sales_query, settings=settings)
        assert result.row_count == len(frame)
        assert result.trends
        assert result.segments

    def test_dataset_without_dates_skips_trends(self, settings):
        frame = make_frame({
            "cat": ["a", "b", "c"] * 20,
            "val": [str(i) for i in range(60)],
        })
        profile = profile_of(frame, settings)
        typed = _typed(frame, profile)
        with DatasetQuery(typed) as query:
            result = run_analysis(typed, profile, query, settings=settings)
        assert result.trends == []
        assert any("date column" in n for n in result.notes)

    def test_categorical_only_dataset_still_segments(self, settings):
        frame = make_frame({
            "country": ["DE", "FR", "ES"] * 30,
            "tier": ["gold", "silver", "bronze"] * 30,
        })
        profile = profile_of(frame, settings)
        typed = _typed(frame, profile)
        with DatasetQuery(typed) as query:
            result = run_analysis(typed, profile, query, settings=settings)
        assert result.segments
        assert result.correlations == []

    def test_evidence_bundle_is_serialisable(self, clean_sales, sales_query, settings):
        import json

        frame, profile, _ = clean_sales
        result = run_analysis(frame, profile, sales_query, settings=settings)
        json.dumps(result.evidence_bundle(), default=str)


class TestRankMeasures:
    def test_primary_measure_leads(self, settings):
        frame = make_frame({
            "cost": [str(i) for i in range(60)],
            "revenue": [str(i * 3) for i in range(60)],
            "unit_price": [str(i + 1) for i in range(60)],
        })
        profile = profile_of(frame, settings)
        ranked = rank_measures(profile, ["cost", "revenue", "unit_price"])
        assert ranked[0] == "revenue"
        # Per-unit values are averaged, so they rank behind additive measures.
        assert ranked[-1] == "unit_price"


def _typed(frame, profile):
    """Apply the profile's detected types, as the cleaner would."""
    from app.cleaning.cleaner import clean_dataset
    from app.config import Settings

    return clean_dataset(frame, profile, settings=Settings()).frame
