"""Cleaning behaviour and the auditability guarantees around it."""

from __future__ import annotations

import pandas as pd
import pytest

from app.cleaning.cleaner import DUPLICATE_SAFETY_THRESHOLD, clean_dataset
from app.schemas.enums import CleaningActionType
from conftest import make_frame, profile_of


def clean(frame, settings):
    profile = profile_of(frame, settings)
    return clean_dataset(frame, profile, settings=settings)


class TestTypeCommitment:
    def test_currency_becomes_numeric(self, settings):
        frame = make_frame({"revenue": ["$1,200.50", "$840.00", "$95.25", "$3,010"]})
        result = clean(frame, settings)
        assert pd.api.types.is_numeric_dtype(result.frame["revenue"])
        assert float(result.frame["revenue"].iloc[0]) == pytest.approx(1200.50)

    def test_parenthesised_negatives(self, settings):
        frame = make_frame({"amount": ["($500.00)", "$250.00", "($75.50)", "$900"]})
        result = clean(frame, settings)
        assert float(result.frame["amount"].iloc[0]) == pytest.approx(-500.0)

    def test_percent_strings_keep_their_scale(self, settings):
        frame = make_frame({"rate": ["10%", "25%", "5%", "50%"]})
        result = clean(frame, settings)
        assert float(result.frame["rate"].iloc[1]) == pytest.approx(25.0)

    def test_dates_are_parsed(self, settings):
        frame = make_frame({"order_date": ["2024-01-05", "2024-02-11", "2024-03-19"]})
        result = clean(frame, settings)
        assert pd.api.types.is_datetime64_any_dtype(result.frame["order_date"])

    def test_mixed_date_formats_do_not_lose_rows(self, settings):
        """Regression: a single-format parse silently dropped 14% of dates."""
        values = ["2024-01-0{}".format(i) for i in range(1, 9)] + [
            "05/29/2024", "03/06/2024", "09/25/2024",
        ]
        frame = make_frame({"order_date": values})
        result = clean(frame, settings)
        assert result.frame["order_date"].notna().all()
        # 03/06 must stay March 6th, not June 3rd.
        parsed = result.frame["order_date"].tolist()
        assert pd.Timestamp("2024-03-06") in parsed

    def test_booleans_are_cast(self, settings):
        frame = make_frame({"returned": ["Yes", "No", "Yes", "No"]})
        result = clean(frame, settings)
        assert pd.api.types.is_bool_dtype(result.frame["returned"])


class TestDuplicates:
    def test_removes_exact_duplicates_when_an_id_exists(self, settings, sales_frame):
        result = clean(sales_frame, settings)
        assert result.report.duplicates_removed == 1
        assert result.report.rows_after == result.report.rows_before - 1
        assert any(
            a.action == CleaningActionType.DROP_DUPLICATES for a in result.report.actions
        )

    def test_keeps_repeated_rows_without_an_identifier(self, settings):
        """A survey-shaped table legitimately repeats combinations.

        Regression: de-duplicating one of these collapsed 400 rows to 36.
        """
        frame = make_frame({
            "country": ["Germany", "France", "Spain", "Italy"] * 100,
            "status": ["active", "churned", "trial", "active"] * 100,
        })
        result = clean(frame, settings)
        assert result.report.rows_after == 400
        assert result.report.duplicates_removed == 0
        assert any("repeated rows" in w for w in result.report.warnings)

    def test_threshold_is_documented(self):
        assert 0 < DUPLICATE_SAFETY_THRESHOLD < 1


class TestMissingValues:
    def test_numeric_missing_values_are_never_imputed(self, settings):
        # The id column keeps the two gap rows from being exact duplicates of
        # each other, which would otherwise be de-duplicated before this check.
        frame = make_frame({
            "order_id": ["A", "B", "C", "D", "E"],
            "revenue": ["100", None, "300", None, "500"],
        })
        result = clean(frame, settings)
        assert result.frame["revenue"].isna().sum() == 2
        strategy = next(
            m.strategy for m in result.report.missing_summary if m.column == "revenue"
        )
        assert "never imputed" in strategy

    def test_categorical_gaps_get_an_explicit_label(self, settings):
        values = ["North", "South", None, "East"] + ["North"] * 16
        frame = make_frame({"region": values})
        result = clean(frame, settings)
        assert "Unknown" in result.frame["region"].tolist()
        assert any(
            a.action == CleaningActionType.FILL_MISSING for a in result.report.actions
        )

    def test_mostly_empty_column_is_dropped_with_a_reason(self, settings):
        frame = make_frame({
            "keep": [str(i) for i in range(20)],
            "sparse": [None] * 19 + ["x"],
        })
        result = clean(frame, settings)
        assert "sparse" in result.report.dropped_columns
        action = next(
            a for a in result.report.actions
            if a.action == CleaningActionType.DROP_COLUMN
        )
        assert "empty" in action.reason


class TestNormalisation:
    def test_whitespace_is_trimmed(self, settings):
        frame = make_frame({"region": [" North ", "North", "North  East", "South"] * 5})
        result = clean(frame, settings)
        assert "North" in result.frame["region"].tolist()
        assert not any(
            str(v).startswith(" ") for v in result.frame["region"].dropna()
        )

    def test_case_variants_are_merged(self, settings):
        frame = make_frame({"region": ["North", "north", "NORTH", "South"] * 5})
        result = clean(frame, settings)
        assert result.frame["region"].nunique() == 2
        assert any(
            a.action == CleaningActionType.NORMALIZE_CATEGORY
            for a in result.report.actions
        )

    def test_placeholder_tokens_become_missing(self, settings):
        frame = make_frame({"note": ["ok", "-", "N/A", "fine", "null"] * 4})
        result = clean(frame, settings)
        assert result.frame["note"].isna().sum() > 0 or "Unknown" in result.frame["note"].tolist()


class TestReport:
    def test_every_action_carries_a_reason_and_a_count(self, settings, sales_frame):
        result = clean(sales_frame, settings)
        assert result.report.actions
        for action in result.report.actions:
            assert action.reason
            assert action.rows_affected >= 0

    def test_scores_are_in_range(self, settings, sales_frame):
        report = clean(sales_frame, settings).report
        for score in (
            report.quality_score,
            report.completeness_score,
            report.uniqueness_score,
            report.consistency_score,
        ):
            assert 0.0 <= score <= 100.0

    def test_clean_data_scores_highly(self, settings):
        frame = make_frame({
            "id": [f"K{i}" for i in range(50)],
            "value": [str(i * 10) for i in range(50)],
        })
        assert clean(frame, settings).report.quality_score > 90

    def test_row_and_column_counts_are_recorded(self, settings, sales_frame):
        report = clean(sales_frame, settings).report
        assert report.rows_before == len(sales_frame)
        assert report.columns_before == sales_frame.shape[1]
        assert report.rows_after <= report.rows_before


class TestEdgeCases:
    def test_single_row_dataset(self, settings):
        frame = make_frame({"a": ["1"], "b": ["x"]})
        result = clean(frame, settings)
        assert len(result.frame) == 1

    def test_only_numeric_columns(self, settings):
        frame = make_frame({f"s{i}": [str(j) for j in range(30)] for i in range(4)})
        result = clean(frame, settings)
        assert result.frame.shape == (30, 4)

    def test_warns_when_no_measure_exists(self, settings):
        frame = make_frame({"a": ["x", "y", "z"] * 10, "b": ["p", "q", "r"] * 10})
        result = clean(frame, settings)
        assert any("numeric measure" in w for w in result.report.warnings)
