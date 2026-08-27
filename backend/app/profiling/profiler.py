"""Dataset profiling: physical types, statistics and semantic roles.

The profiler is read-only. It looks at a raw (all-string) frame and reports
what it finds; the cleaner is the only component allowed to mutate data.
"""

from __future__ import annotations

import pandas as pd

from ..config import Settings
from ..schemas.enums import DIMENSION_ROLES, MEASURE_ROLES, InferredType, SemanticRole
from ..schemas.profile import (
    ColumnProfile,
    DatasetProfile,
    DatetimeStats,
    NumericStats,
    ValueCount,
)
from ..utils import coercion
from ..utils.logging import get_logger
from ..utils.serialization import safe_float
from . import semantics

log = get_logger(__name__)

TEXT_LENGTH_THRESHOLD = 60
TEXT_WORD_THRESHOLD = 6


def detect_type(
    series: pd.Series, name: str, *, settings: Settings
) -> tuple[InferredType, dict[str, object]]:
    """Decide the physical type of a raw column."""
    values = coercion.non_null(series)
    meta: dict[str, object] = {}
    if values.empty:
        return InferredType.EMPTY, meta

    unique = int(values.nunique())

    boolean = coercion.try_boolean(series)
    if boolean.detected:
        meta["boolean"] = boolean
        return InferredType.BOOLEAN, meta

    datetime_result = coercion.try_datetime(series, name)
    if datetime_result.detected:
        meta["datetime"] = datetime_result
        return InferredType.DATETIME, meta

    numeric = coercion.try_numeric(series)
    if numeric.detected:
        meta["numeric"] = numeric
        return InferredType.NUMERIC, meta

    # Text vs categorical: long free-form strings are text, short repeated
    # labels are categorical.
    sample = values.head(500).astype(str)
    avg_len = float(sample.str.len().mean())
    avg_words = float(sample.str.split().str.len().mean())
    non_null_count = len(values)
    ratio = unique / non_null_count if non_null_count else 0.0

    if avg_len > TEXT_LENGTH_THRESHOLD or avg_words > TEXT_WORD_THRESHOLD:
        return InferredType.TEXT, meta
    if unique > settings.max_categorical_cardinality and ratio > settings.high_cardinality_threshold:
        return InferredType.TEXT, meta
    return InferredType.CATEGORICAL, meta


def _numeric_stats(values: pd.Series) -> NumericStats:
    clean = values.dropna()
    if clean.empty:
        return NumericStats()
    desc = clean.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
    q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    iqr = q3 - q1
    if iqr > 0:
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = int(((clean < lo) | (clean > hi)).sum())
    else:
        outliers = 0
    return NumericStats(
        min=safe_float(desc.get("min")),
        max=safe_float(desc.get("max")),
        mean=safe_float(desc.get("mean")),
        median=safe_float(clean.median()),
        std=safe_float(desc.get("std")),
        p05=safe_float(desc.get("5%")),
        p25=safe_float(desc.get("25%")),
        p75=safe_float(desc.get("75%")),
        p95=safe_float(desc.get("95%")),
        skew=safe_float(clean.skew()) if len(clean) > 2 else None,
        sum=safe_float(clean.sum()),
        zero_pct=round(float((clean == 0).mean()) * 100, 2),
        negative_pct=round(float((clean < 0).mean()) * 100, 2),
        outlier_count=outliers,
    )


def _datetime_stats(values: pd.Series) -> DatetimeStats:
    clean = values.dropna()
    if clean.empty:
        return DatetimeStats()
    lo, hi = clean.min(), clean.max()
    span = (hi - lo).days
    distinct_days = int(clean.dt.normalize().nunique())
    if span <= 0:
        grain = "day"
    elif span <= 62:
        grain = "day"
    elif span <= 400:
        grain = "week" if distinct_days > 60 else "month"
    elif span <= 1500:
        grain = "month"
    else:
        grain = "quarter" if span <= 4000 else "year"
    return DatetimeStats(
        min=lo.isoformat(),
        max=hi.isoformat(),
        range_days=int(span),
        suggested_grain=grain,
        distinct_days=distinct_days,
    )


def _top_values(values: pd.Series, limit: int = 12) -> list[ValueCount]:
    if values.empty:
        return []
    counts = values.astype(str).value_counts().head(limit)
    total = len(values)
    return [
        ValueCount(value=str(idx), count=int(cnt), pct=round(cnt / total * 100, 2))
        for idx, cnt in counts.items()
    ]


def profile_column(
    series: pd.Series, name: str, *, n_rows: int, settings: Settings
) -> ColumnProfile:
    values = coercion.non_null(series)
    non_null_count = len(values)
    missing = n_rows - non_null_count
    unique = int(values.nunique()) if non_null_count else 0
    ratio = (unique / non_null_count) if non_null_count else 0.0

    inferred, meta = detect_type(series, name, settings=settings)

    numeric_stats: NumericStats | None = None
    datetime_stats: DatetimeStats | None = None
    numeric_min = numeric_max = None

    if inferred == InferredType.NUMERIC:
        converted = meta["numeric"].series  # type: ignore[index]
        numeric_stats = _numeric_stats(converted)
        numeric_min, numeric_max = numeric_stats.min, numeric_stats.max
        unique = int(converted.dropna().nunique())
        ratio = (unique / non_null_count) if non_null_count else 0.0
    elif inferred == InferredType.DATETIME:
        converted = meta["datetime"].series  # type: ignore[index]
        datetime_stats = _datetime_stats(converted)

    verdict = semantics.infer_role(
        name=name,
        series=series,
        inferred_type=inferred,
        unique=unique,
        non_null_count=non_null_count,
        numeric_min=numeric_min,
        numeric_max=numeric_max,
    )

    top_values: list[ValueCount] = []
    if inferred in (InferredType.CATEGORICAL, InferredType.BOOLEAN):
        top_values = _top_values(values)
    elif inferred == InferredType.TEXT and unique <= settings.max_categorical_cardinality:
        top_values = _top_values(values, limit=8)

    return ColumnProfile(
        name=name,
        original_dtype=str(series.dtype),
        inferred_type=inferred,
        semantic_role=verdict.role,
        role_confidence=verdict.confidence,
        role_evidence=verdict.evidence,
        count=non_null_count,
        missing=missing,
        missing_pct=round((missing / n_rows * 100) if n_rows else 0.0, 2),
        unique=unique,
        cardinality_ratio=round(ratio, 4),
        is_constant=unique <= 1 and non_null_count > 0,
        is_unique_key=(unique == n_rows and n_rows > 1 and missing == 0),
        numeric=numeric_stats,
        datetime=datetime_stats,
        top_values=top_values,
        sample_values=[str(v) for v in values.head(5).tolist()],
    )


def _pick_primary_date(columns: list[ColumnProfile]) -> str | None:
    """Prefer the date column with the widest usable span and fewest gaps."""
    candidates = [
        c
        for c in columns
        if c.inferred_type == InferredType.DATETIME and c.datetime and c.count > 0
    ]
    if not candidates:
        return None

    def score(c: ColumnProfile) -> tuple[float, float, float]:
        name = semantics.normalize(c.name)
        name_bonus = 0.0
        for token, bonus in (
            ("order_date", 3.0), ("transaction_date", 3.0), ("date", 2.0),
            ("created", 1.5), ("hire_date", 2.5), ("timestamp", 1.5),
            ("start", 1.0), ("period", 1.5),
        ):
            if token in name:
                name_bonus = max(name_bonus, bonus)
        completeness = 1.0 - (c.missing_pct / 100.0)
        span = float(c.datetime.range_days or 0)
        return (name_bonus, completeness, span)

    return max(candidates, key=score).name


# Headline measures, in the order a analyst would reach for them. Revenue is a
# better dashboard headline than cost even when cost is more complete.
_MEASURE_NAME_PRIORITY = (
    ("revenue", 10.0), ("sales", 9.5), ("gmv", 9.0), ("amount", 8.0),
    ("salary", 8.5), ("total", 7.5), ("profit", 7.0), ("spend", 6.5),
    ("value", 6.0), ("price", 5.0), ("quantity", 4.5), ("units", 4.5),
    ("cost", 3.0), ("bonus", 2.5), ("tax", 1.0),
)


def _name_priority(name: str, missing_pct: float = 0.0) -> float:
    """Name-based ranking, discounted when the column is mostly empty."""
    norm = semantics.normalize(name)
    best = 0.0
    for token, weight in _MEASURE_NAME_PRIORITY:
        if token in norm:
            best = max(best, weight)
    if missing_pct > 50.0:
        best *= 0.4
    elif missing_pct > 25.0:
        best *= 0.7
    return best


def _pick_primary_measure(columns: list[ColumnProfile]) -> str | None:
    measures = [
        c
        for c in columns
        if c.semantic_role in MEASURE_ROLES
        and c.inferred_type == InferredType.NUMERIC
    ]
    if not measures:
        return None

    def score(c: ColumnProfile) -> tuple[float, int, float, float]:
        role_rank = {
            SemanticRole.CURRENCY: 3,
            SemanticRole.MEASURE: 2,
            SemanticRole.QUANTITY: 2,
            SemanticRole.RATIO: 1,
            SemanticRole.PERCENTAGE: 0,
        }.get(c.semantic_role, 1)
        completeness = 1.0 - (c.missing_pct / 100.0)
        magnitude = abs(c.numeric.sum or 0.0) if c.numeric else 0.0
        return (_name_priority(c.name, c.missing_pct), role_rank, completeness, magnitude)

    return max(measures, key=score).name


def profile_dataset(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    name: str,
    settings: Settings,
) -> DatasetProfile:
    n_rows = len(frame)
    columns = [
        profile_column(frame[col], col, n_rows=n_rows, settings=settings)
        for col in frame.columns
    ]

    duplicates = int(frame.duplicated().sum())
    domain, signals = semantics.guess_domain([c.name for c in columns])

    by_type: dict[InferredType, list[str]] = {t: [] for t in InferredType}
    for c in columns:
        by_type[c.inferred_type].append(c.name)

    identifiers = [c.name for c in columns if c.semantic_role == SemanticRole.IDENTIFIER]
    measures = [
        c.name
        for c in columns
        if c.semantic_role in MEASURE_ROLES and c.inferred_type == InferredType.NUMERIC
    ]
    dimensions = [
        c.name
        for c in columns
        if c.semantic_role in DIMENSION_ROLES
        and c.inferred_type in (InferredType.CATEGORICAL, InferredType.BOOLEAN)
    ]

    profile = DatasetProfile(
        dataset_id=dataset_id,
        name=name,
        n_rows=n_rows,
        n_columns=len(columns),
        n_duplicate_rows=duplicates,
        memory_bytes=int(frame.memory_usage(deep=True).sum()),
        columns=columns,
        numeric_columns=by_type[InferredType.NUMERIC],
        categorical_columns=by_type[InferredType.CATEGORICAL],
        datetime_columns=by_type[InferredType.DATETIME],
        boolean_columns=by_type[InferredType.BOOLEAN],
        text_columns=by_type[InferredType.TEXT],
        identifier_columns=identifiers,
        measure_columns=measures,
        dimension_columns=dimensions,
        primary_date_column=_pick_primary_date(columns),
        primary_measure_column=_pick_primary_measure(columns),
        domain_guess=domain,
        domain_signals=signals,
    )
    log.info(
        "Profiled %s: %d rows, %d cols, domain=%s, measures=%d, dims=%d",
        name, n_rows, len(columns), domain, len(measures), len(dimensions),
    )
    return profile
