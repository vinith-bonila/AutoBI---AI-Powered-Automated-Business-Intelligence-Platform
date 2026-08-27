"""Shared fixtures.

Tests build frames in memory wherever possible so they stay fast and do not
depend on the generated sample files. The API tests use the real sample CSVs
because their whole point is to exercise the production path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis.query import DatasetQuery  # noqa: E402
from app.cleaning.cleaner import clean_dataset  # noqa: E402
from app.config import Settings  # noqa: E402
from app.profiling.profiler import profile_dataset  # noqa: E402

SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway storage directory."""
    return Settings(
        storage_dir=tmp_path / "storage",
        ai_provider="none",
        ai_api_key="",
    )


@pytest.fixture
def sales_frame() -> pd.DataFrame:
    """A small, deliberately messy sales extract.

    Contains: currency strings, percent strings, a mixed date format, a
    duplicate row, missing values, and inconsistent category casing.
    """
    rows = [
        ("ORD-1", "2024-01-05", "North", "Widget", "$1,200.50", "10%", "3", "Yes"),
        ("ORD-2", "2024-01-19", "south", "Gadget", "$840.00", "0%", "1", "No"),
        ("ORD-3", "02/14/2024", "North", "Widget", "$2,300.75", "15%", "5", "No"),
        ("ORD-4", "2024-02-28", " North ", "Doohickey", "$150.00", "5%", "2", "No"),
        ("ORD-5", "2024-03-11", "East", "Gadget", "", "0%", "1", "No"),
        ("ORD-6", "2024-03-22", "West", "Widget", "$3,010.25", "20%", "8", "Yes"),
        ("ORD-7", "2024-04-02", "South", "Doohickey", "$95.00", "0%", "1", "No"),
        ("ORD-8", "2024-04-18", "East", "Widget", "$1,750.00", "10%", "4", "No"),
        ("ORD-9", "2024-05-09", "West", "Gadget", "$620.40", "5%", "2", "No"),
        ("ORD-10", "2024-05-27", "North", "Widget", "$2,480.00", "25%", "6", "Yes"),
        ("ORD-11", "2024-06-14", "", "Gadget", "$310.00", "0%", "1", "No"),
        ("ORD-12", "2024-06-30", "South", "Doohickey", "$1,120.60", "10%", "3", "No"),
    ]
    # A genuine duplicate of ORD-2, which the cleaner should remove.
    rows.append(rows[1])
    return pd.DataFrame(
        rows,
        columns=[
            "order_id", "order_date", "region", "product",
            "revenue", "discount_pct", "quantity", "returned",
        ],
    ).astype("string")


@pytest.fixture
def clean_sales(sales_frame: pd.DataFrame, settings: Settings):
    """The sales frame after the full profile -> clean -> re-profile cycle."""
    raw_profile = profile_dataset(
        sales_frame, dataset_id="test", name="sales.csv", settings=settings
    )
    result = clean_dataset(sales_frame, raw_profile, settings=settings)
    profile = profile_dataset(
        result.frame, dataset_id="test", name="sales.csv", settings=settings
    )
    return result.frame, profile, result.report


@pytest.fixture
def sales_query(clean_sales):
    frame, _, _ = clean_sales
    query = DatasetQuery(frame)
    yield query
    query.close()


def make_frame(data: dict[str, list]) -> pd.DataFrame:
    """Build an all-string frame, matching what the CSV reader produces."""
    return pd.DataFrame(data).astype("string")


def profile_of(frame: pd.DataFrame, settings: Settings, name: str = "t.csv"):
    return profile_dataset(frame, dataset_id="t", name=name, settings=settings)
