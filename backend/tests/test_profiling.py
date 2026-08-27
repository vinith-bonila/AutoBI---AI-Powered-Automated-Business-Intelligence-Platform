"""Type detection, semantic role inference and dataset-level profiling."""

from __future__ import annotations

import pandas as pd
import pytest

from app.profiling.profiler import profile_dataset
from app.profiling.semantics import guess_domain, match_strength, normalize
from app.schemas.enums import InferredType, SemanticRole
from conftest import make_frame, profile_of


class TestTypeDetection:
    def test_detects_numeric_with_currency(self, settings):
        frame = make_frame({"revenue": ["$1,200.50", "$840.00", "$95.25", "$3,010"]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.NUMERIC
        assert column.semantic_role == SemanticRole.CURRENCY

    def test_detects_percent_strings(self, settings):
        frame = make_frame({"ctr": ["4.20%", "3.10%", "5.75%", "2.00%"]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.NUMERIC
        assert column.semantic_role == SemanticRole.PERCENTAGE

    def test_detects_dates(self, settings):
        frame = make_frame({"order_date": ["2024-01-05", "2024-02-11", "2024-03-19"]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.DATETIME
        assert column.semantic_role == SemanticRole.TIME

    def test_detects_boolean(self, settings):
        frame = make_frame({"active": ["Yes", "No", "Yes", "No", "Yes"]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.BOOLEAN
        assert column.semantic_role == SemanticRole.FLAG

    def test_detects_categorical(self, settings):
        frame = make_frame({"region": ["North", "South", "North", "East"] * 5})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.CATEGORICAL

    def test_long_strings_are_text_not_categories(self, settings):
        frame = make_frame({
            "comment": [
                "The delivery arrived two days later than the estimate given",
                "Customer service resolved my issue quickly and politely today",
                "Packaging was damaged although the product itself was fine",
            ]
        })
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.TEXT

    def test_numeric_id_is_not_a_date(self, settings):
        """Eight-digit ids must not be mistaken for yyyymmdd dates."""
        frame = make_frame({"customer_id": [str(90000000 + i) for i in range(40)]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type != InferredType.DATETIME

    def test_empty_column(self, settings):
        frame = make_frame({"blank": [None, None, None, None]})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type == InferredType.EMPTY

    def test_mixed_garbage_stays_categorical(self, settings):
        frame = make_frame({"mixed": ["12", "abc", "3.5", "xyz", "7", "def"] * 4})
        column = profile_of(frame, settings).columns[0]
        assert column.inferred_type in (InferredType.CATEGORICAL, InferredType.TEXT)


class TestSemanticRoles:
    def test_identifier_by_name_and_cardinality(self, settings):
        frame = make_frame({"order_id": [f"ORD-{i}" for i in range(50)]})
        column = profile_of(frame, settings).columns[0]
        assert column.semantic_role == SemanticRole.IDENTIFIER

    def test_uuid_is_identifier(self, settings):
        uuids = [f"{i:08x}-1234-5678-9abc-def012345678" for i in range(30)]
        column = profile_of(make_frame({"ref": uuids}), settings).columns[0]
        assert column.semantic_role == SemanticRole.IDENTIFIER

    def test_geo_dimension(self, settings):
        frame = make_frame({"country": ["Germany", "France", "Spain"] * 10})
        column = profile_of(frame, settings).columns[0]
        assert column.semantic_role == SemanticRole.GEO

    def test_quantity_beats_percent_for_conversions(self, settings):
        """`conversions` is a count, even though `conversion` is a rate word."""
        frame = make_frame({"conversions": [str(i * 3) for i in range(1, 60)]})
        column = profile_of(frame, settings).columns[0]
        assert column.semantic_role == SemanticRole.QUANTITY

    def test_rating_scale_is_not_a_percentage(self, settings):
        """`satisfaction_rating` of 1-5 is an ordinal scale, not a percent."""
        frame = make_frame({"satisfaction_rating": ["1", "2", "3", "4", "5"] * 40})
        column = profile_of(frame, settings).columns[0]
        assert column.semantic_role != SemanticRole.PERCENTAGE

    def test_role_evidence_is_recorded(self, settings):
        frame = make_frame({"revenue": ["$10.00", "$20.00", "$30.00"]})
        column = profile_of(frame, settings).columns[0]
        assert column.role_evidence
        assert 0.0 <= column.role_confidence <= 1.0


class TestDatasetProfile:
    def test_counts_and_duplicates(self, settings):
        frame = make_frame({"a": ["1", "2", "2"], "b": ["x", "y", "y"]})
        profile = profile_of(frame, settings)
        assert profile.n_rows == 3
        assert profile.n_columns == 2
        assert profile.n_duplicate_rows == 1

    def test_missing_percentage(self, settings):
        frame = make_frame({"a": ["1", None, "3", None]})
        column = profile_of(frame, settings).columns[0]
        assert column.missing == 2
        assert column.missing_pct == 50.0

    def test_primary_measure_prefers_revenue_over_cost(self, settings):
        frame = make_frame({
            "cost": [str(i) for i in range(60)],
            "revenue": [str(i * 2) for i in range(60)],
        })
        profile = profile_of(frame, settings)
        assert profile.primary_measure_column == "revenue"

    def test_primary_date_is_selected(self, settings):
        frame = make_frame({
            "order_date": pd.date_range("2024-01-01", periods=40).astype(str).tolist(),
            "value": [str(i) for i in range(40)],
        })
        profile = profile_of(frame, settings)
        assert profile.primary_date_column == "order_date"

    def test_constant_column_flagged(self, settings):
        frame = make_frame({"same": ["x"] * 20})
        column = profile_of(frame, settings).columns[0]
        assert column.is_constant

    def test_unique_key_flagged(self, settings):
        frame = make_frame({"pk": [f"K{i}" for i in range(30)]})
        column = profile_of(frame, settings).columns[0]
        assert column.is_unique_key

    def test_compact_view_is_llm_ready(self, settings, sales_frame):
        profile = profile_of(sales_frame, settings)
        compact = profile.compact()
        assert compact["rows"] == len(sales_frame)
        assert {f["name"] for f in compact["fields"]} == set(sales_frame.columns)


class TestDomainDetection:
    @pytest.mark.parametrize(
        "columns,expected",
        [
            (["order_id", "revenue", "quantity", "discount", "profit"], "sales"),
            (["employee_id", "department", "salary", "hire_date", "attrition"], "hr"),
            (["campaign", "impressions", "clicks", "ctr", "spend"], "marketing"),
            (["transaction_id", "account", "balance", "invoice", "ledger"], "finance"),
        ],
    )
    def test_recognises_domains(self, columns, expected):
        domain, signals = guess_domain(columns)
        assert domain == expected
        assert signals

    def test_unknown_columns_fall_back_to_general(self):
        domain, _ = guess_domain(["alpha", "beta", "gamma"])
        assert domain == "general"


class TestMatchStrength:
    def test_exact_token_beats_substring(self):
        exact, _ = match_strength("total_orders", {"orders"})
        substring, _ = match_strength("conversions", {"conversion"})
        assert exact > substring

    def test_normalize(self):
        assert normalize("Total Revenue (USD)") == "total_revenue_usd"
