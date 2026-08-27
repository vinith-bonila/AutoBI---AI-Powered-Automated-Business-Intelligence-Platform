"""Exploratory data analysis engine.

Everything the dashboard claims as fact is computed here, in Python, from the
cleaned dataset. The LLM later *narrates* these numbers but never produces
them. Analyses that do not apply to a dataset are simply skipped — a dataset
with no dates gets no trend section rather than an empty one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from ..config import Settings
from ..schemas.analysis import (
    AnalysisResult,
    AnomalyReport,
    CorrelationPair,
    DistributionSummary,
    OutlierReport,
    SegmentAnalysis,
    SegmentRow,
    TrendAnalysis,
    TrendPoint,
)
from ..schemas.enums import Aggregation, InferredType, SemanticRole, TimeGrain
from ..schemas.profile import DatasetProfile
from ..utils.logging import get_logger
from ..utils.serialization import safe_float
from .query import DatasetQuery

log = get_logger(__name__)

MIN_ROWS_FOR_CORRELATION = 20
MIN_PERIODS_FOR_TREND = 3
STRONG_CORRELATION = 0.7
MODERATE_CORRELATION = 0.4
ANOMALY_Z_THRESHOLD = 2.5
# A final period holding less than this share of a typical period's rows is
# treated as incomplete and excluded from the headline change.
PARTIAL_PERIOD_RATIO = 0.6


def _grain_from_string(value: str | None) -> TimeGrain:
    try:
        return TimeGrain(value or "month")
    except ValueError:
        return TimeGrain.MONTH


def _format_period(value: pd.Timestamp, grain: TimeGrain) -> str:
    if grain == TimeGrain.YEAR:
        return value.strftime("%Y")
    if grain == TimeGrain.QUARTER:
        return f"{value.year} Q{((value.month - 1) // 3) + 1}"
    if grain == TimeGrain.MONTH:
        return value.strftime("%Y-%m")
    return value.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# correlations
# --------------------------------------------------------------------------


def analyze_correlations(
    frame: pd.DataFrame, profile: DatasetProfile, *, max_pairs: int = 12
) -> list[CorrelationPair]:
    """Pearson correlations between meaningful numeric columns."""
    candidates = [
        c.name
        for c in profile.columns
        if c.inferred_type == InferredType.NUMERIC
        and c.semantic_role != SemanticRole.IDENTIFIER
        and not c.is_constant
        and c.name in frame.columns
    ]
    if len(candidates) < 2 or len(frame) < MIN_ROWS_FOR_CORRELATION:
        return []

    numeric = frame[candidates].apply(pd.to_numeric, errors="coerce").astype("float64")
    pairs: list[CorrelationPair] = []

    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            joint = numeric[[a, b]].dropna()
            if len(joint) < MIN_ROWS_FOR_CORRELATION:
                continue
            if joint[a].nunique() < 3 or joint[b].nunique() < 3:
                continue
            try:
                coef, p_value = scipy_stats.pearsonr(joint[a], joint[b])
            except (ValueError, FloatingPointError):
                continue
            coef = safe_float(coef)
            if coef is None:
                continue
            magnitude = abs(coef)
            if magnitude < MODERATE_CORRELATION:
                continue
            pairs.append(
                CorrelationPair(
                    x=a,
                    y=b,
                    coefficient=round(coef, 4),
                    strength=(
                        "strong"
                        if magnitude >= STRONG_CORRELATION
                        else "moderate"
                    ),
                    direction="positive" if coef > 0 else "negative",
                    p_value=safe_float(p_value),
                    n=len(joint),
                )
            )

    pairs.sort(key=lambda p: -abs(p.coefficient))
    return pairs[:max_pairs]


# --------------------------------------------------------------------------
# trends
# --------------------------------------------------------------------------


def analyze_trend(
    query: DatasetQuery,
    *,
    date_column: str,
    measure: str | None,
    aggregation: Aggregation,
    grain: TimeGrain,
) -> TrendAnalysis | None:
    """Aggregate a measure over time and describe its shape."""
    try:
        df = query.time_series(date_column, measure, aggregation, grain)
    except Exception as exc:  # QueryError or dtype issue
        log.debug("Trend skipped for %s: %s", measure, exc)
        return None

    df = df.dropna(subset=["period"])
    if len(df) < MIN_PERIODS_FOR_TREND:
        return None

    df = df.sort_values("period")
    values = pd.to_numeric(df["value"], errors="coerce")
    mask = values.notna()
    df, values = df[mask], values[mask]
    if len(df) < MIN_PERIODS_FOR_TREND:
        return None

    # A dataset almost never ends exactly on a period boundary, so the final
    # bucket is usually partial. Reporting it as the "latest value" invents a
    # dramatic decline that does not exist, so drop it when it is clearly
    # under-filled relative to the periods before it.
    partial_period: str | None = None
    if "row_count" in df.columns and len(df) > MIN_PERIODS_FOR_TREND:
        counts = pd.to_numeric(df["row_count"], errors="coerce")
        typical = float(counts.iloc[:-1].median())
        last_count = float(counts.iloc[-1])
        if typical > 0 and last_count < typical * PARTIAL_PERIOD_RATIO:
            partial_period = _format_period(pd.Timestamp(df["period"].iloc[-1]), grain)
            df, values = df.iloc[:-1], values.iloc[:-1]
        if len(df) < MIN_PERIODS_FOR_TREND:
            return None

    points = [
        TrendPoint(
            period=_format_period(pd.Timestamp(p), grain),
            value=round(float(v), 4),
        )
        for p, v in zip(df["period"], values)
    ]

    first, last = float(values.iloc[0]), float(values.iloc[-1])
    change_pct = ((last - first) / abs(first) * 100) if first else None

    # Linear fit over the period index describes the overall direction.
    x = np.arange(len(values), dtype="float64")
    slope = r_squared = None
    if len(values) >= 3 and values.std() > 0:
        try:
            reg = scipy_stats.linregress(x, values.to_numpy(dtype="float64"))
            slope = safe_float(reg.slope)
            r_squared = safe_float(reg.rvalue**2)
        except (ValueError, FloatingPointError):
            pass

    if change_pct is None:
        direction = "flat"
    elif change_pct > 5:
        direction = "up"
    elif change_pct < -5:
        direction = "down"
    else:
        direction = "flat"

    best_idx = int(values.to_numpy().argmax())
    worst_idx = int(values.to_numpy().argmin())

    pop = None
    if len(values) >= 2:
        prev, curr = float(values.iloc[-2]), float(values.iloc[-1])
        if prev:
            pop = round((curr - prev) / abs(prev) * 100, 2)

    mean_value = float(values.mean())
    volatility = (
        round(float(values.std()) / abs(mean_value) * 100, 2) if mean_value else None
    )

    return TrendAnalysis(
        measure=measure or "row count",
        date_column=date_column,
        grain=grain.value,
        points=points,
        first_value=round(first, 4),
        last_value=round(last, 4),
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        direction=direction,
        slope=slope,
        r_squared=r_squared,
        best_period=points[best_idx],
        worst_period=points[worst_idx],
        period_over_period_pct=pop,
        volatility_pct=volatility,
        partial_period_excluded=partial_period,
    )


def detect_anomalies(trend: TrendAnalysis, *, limit: int = 4) -> list[AnomalyReport]:
    """Flag periods far from a rolling local expectation."""
    if len(trend.points) < 6:
        return []
    series = pd.Series([p.value for p in trend.points], dtype="float64")
    window = max(3, min(7, len(series) // 3))
    rolling = series.rolling(window=window, center=True, min_periods=2).median()
    residual = series - rolling
    std = float(residual.std())
    if not std or np.isnan(std):
        return []

    anomalies: list[AnomalyReport] = []
    for idx, (actual, expected, diff) in enumerate(zip(series, rolling, residual)):
        if np.isnan(expected) or np.isnan(diff):
            continue
        z = float(diff) / std
        if abs(z) < ANOMALY_Z_THRESHOLD:
            continue
        deviation = ((actual - expected) / abs(expected) * 100) if expected else 0.0
        anomalies.append(
            AnomalyReport(
                measure=trend.measure,
                period=trend.points[idx].period,
                value=round(float(actual), 4),
                expected=round(float(expected), 4),
                deviation_pct=round(deviation, 2),
                z_score=round(z, 2),
            )
        )

    anomalies.sort(key=lambda a: -abs(a.z_score))
    return anomalies[:limit]


# --------------------------------------------------------------------------
# segments
# --------------------------------------------------------------------------


def analyze_segment(
    query: DatasetQuery,
    *,
    dimension: str,
    measure: str | None,
    aggregation: Aggregation,
    top_n: int = 8,
) -> SegmentAnalysis | None:
    try:
        df = query.aggregate_by_dimension(
            dimension, measure, aggregation, limit=1000, sort="value_desc"
        )
    except Exception as exc:
        log.debug("Segment skipped for %s: %s", dimension, exc)
        return None

    df = df.dropna(subset=["value"])
    if df.empty or len(df) < 2:
        return None

    values = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    n_categories = len(df)

    # With mixed signs (a ledger of income and expenses) the signed total is a
    # near-zero net figure, and dividing by it yields shares like 150%. Fall
    # back to total magnitude so "share" stays interpretable.
    has_negative = bool((values < 0).any())
    signed_total = float(values.sum())
    total = float(values.abs().sum()) if has_negative else signed_total
    share_basis = "absolute_total" if has_negative else "total"

    def rows(subset: pd.DataFrame) -> list[SegmentRow]:
        out = []
        for record in subset.itertuples():
            value = float(getattr(record, "value") or 0.0)
            share = (abs(value) if has_negative else value) / total * 100 if total else 0.0
            out.append(
                SegmentRow(
                    label=str(record.label),
                    value=round(value, 4),
                    share_pct=round(share, 2),
                    count=int(getattr(record, "row_count", 0) or 0),
                )
            )
        return out

    top = rows(df.head(top_n))
    bottom = rows(df.tail(min(3, max(0, n_categories - top_n))))
    concentration = round(sum(r.share_pct for r in top[:3]), 2) if total else None

    # Gini coefficient describes how unevenly the measure is distributed.
    gini = None
    if total > 0 and n_categories > 2 and not has_negative:
        sorted_values = np.sort(values.to_numpy(dtype="float64"))
        n = len(sorted_values)
        index = np.arange(1, n + 1)
        gini = safe_float(
            (np.sum((2 * index - n - 1) * sorted_values)) / (n * np.sum(sorted_values))
        )
        gini = round(gini, 4) if gini is not None else None

    return SegmentAnalysis(
        dimension=dimension,
        measure=measure or "row count",
        aggregation=aggregation.value,
        top=top,
        bottom=bottom,
        n_categories=n_categories,
        concentration_pct=concentration,
        gini=gini,
        has_negative_values=has_negative,
        share_basis=share_basis,
    )


# --------------------------------------------------------------------------
# outliers & distributions
# --------------------------------------------------------------------------


def analyze_outliers(
    frame: pd.DataFrame, profile: DatasetProfile, *, limit: int = 6
) -> list[OutlierReport]:
    reports: list[OutlierReport] = []
    for col in profile.columns:
        if (
            col.inferred_type != InferredType.NUMERIC
            or col.semantic_role == SemanticRole.IDENTIFIER
            or col.name not in frame.columns
            or col.is_constant
        ):
            continue
        values = pd.to_numeric(frame[col.name], errors="coerce").dropna()
        if len(values) < 20:
            continue
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (values < lower) | (values > upper)
        count = int(mask.sum())
        if not count:
            continue
        extreme = values[mask].abs().nlargest(5)
        reports.append(
            OutlierReport(
                column=col.name,
                method="iqr",
                count=count,
                pct=round(count / len(values) * 100, 2),
                lower_bound=round(lower, 4),
                upper_bound=round(upper, 4),
                extreme_values=[round(float(v), 4) for v in values[mask].nlargest(3)]
                + [round(float(v), 4) for v in values[mask].nsmallest(2)],
            )
        )

    reports.sort(key=lambda r: -r.pct)
    return reports[:limit]


def analyze_distributions(
    frame: pd.DataFrame, profile: DatasetProfile, *, limit: int = 6
) -> list[DistributionSummary]:
    summaries: list[DistributionSummary] = []
    for col in profile.columns:
        if (
            col.inferred_type != InferredType.NUMERIC
            or col.semantic_role == SemanticRole.IDENTIFIER
            or col.name not in frame.columns
            or col.is_constant
        ):
            continue
        values = pd.to_numeric(frame[col.name], errors="coerce").dropna()
        if len(values) < 20 or values.nunique() < 4:
            continue
        skew = safe_float(values.skew())
        kurt = safe_float(values.kurtosis())

        if skew is None:
            shape = "unknown"
        elif skew > 1.0:
            shape = "right-skewed"
        elif skew < -1.0:
            shape = "left-skewed"
        elif kurt is not None and kurt < -1.0:
            shape = "uniform-ish"
        else:
            shape = "normal-ish"

        counts, edges = np.histogram(values.to_numpy(dtype="float64"), bins=20)
        summaries.append(
            DistributionSummary(
                column=col.name,
                shape=shape,
                skew=round(skew, 4) if skew is not None else None,
                kurtosis=round(kurt, 4) if kurt is not None else None,
                bins=[round(float(e), 4) for e in edges],
                counts=[int(c) for c in counts],
            )
        )
    return summaries[:limit]


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


# Per-unit and per-row quantities are meaningless when summed: the total of a
# `unit_price` column is not a business figure, its average is.
_AVERAGE_NAME_TOKENS = (
    "price", "rate", "score", "age", "tenure", "level", "ratio", "margin",
    "index", "per_", "avg", "average", "median", "temperature", "rating",
)


def _measure_aggregation(profile: DatasetProfile, column: str) -> Aggregation:
    """Averages suit rates, prices and scores; sums suit money and counts."""
    col = profile.column(column)
    if col is None:
        return Aggregation.SUM
    if col.semantic_role in (
        SemanticRole.PERCENTAGE,
        SemanticRole.RATIO,
        SemanticRole.DEMOGRAPHIC,
    ):
        return Aggregation.AVG
    normalized = column.lower()
    if any(token in normalized for token in _AVERAGE_NAME_TOKENS):
        return Aggregation.AVG
    return Aggregation.SUM


def rank_measures(profile: DatasetProfile, available: list[str]) -> list[str]:
    """Order measures so the dataset's headline figure is analysed first."""
    primary = profile.primary_measure_column
    ordered = sorted(
        available,
        key=lambda name: (
            0 if name == primary else 1,
            # Additive money/count columns make better headline trends than
            # per-unit averages.
            0 if _measure_aggregation(profile, name) == Aggregation.SUM else 1,
            profile.columns.index(profile.column(name)) if profile.column(name) else 99,
        ),
    )
    return ordered


def run_analysis(
    frame: pd.DataFrame,
    profile: DatasetProfile,
    query: DatasetQuery,
    *,
    settings: Settings,
) -> AnalysisResult:
    """Run every analysis that makes sense for this dataset."""
    notes: list[str] = []

    correlations = analyze_correlations(frame, profile)
    if not correlations and len(profile.measure_columns) >= 2:
        notes.append("No numeric relationships passed the correlation threshold.")

    # -- trends ------------------------------------------------------------
    trends: list[TrendAnalysis] = []
    anomalies: list[AnomalyReport] = []
    date_col = profile.primary_date_column
    if date_col:
        col_profile = profile.column(date_col)
        grain = _grain_from_string(
            col_profile.datetime.suggested_grain if col_profile and col_profile.datetime else None
        )
        measures = rank_measures(
            profile, [m for m in profile.measure_columns if m in frame.columns]
        )[:3]
        if not measures:
            trend = analyze_trend(
                query, date_column=date_col, measure=None,
                aggregation=Aggregation.COUNT, grain=grain,
            )
            if trend:
                trends.append(trend)
        for measure in measures:
            trend = analyze_trend(
                query,
                date_column=date_col,
                measure=measure,
                aggregation=_measure_aggregation(profile, measure),
                grain=grain,
            )
            if trend:
                trends.append(trend)
                anomalies.extend(detect_anomalies(trend))
    else:
        notes.append("No usable date column was found, so trend analysis was skipped.")

    # -- segments ----------------------------------------------------------
    segments: list[SegmentAnalysis] = []
    dimensions = [
        c.name
        for c in profile.columns
        if c.name in frame.columns
        and c.inferred_type in (InferredType.CATEGORICAL, InferredType.BOOLEAN)
        and c.semantic_role != SemanticRole.IDENTIFIER
        and 1 < c.unique <= settings.max_categorical_cardinality
        and not c.is_constant
    ]
    primary_measure = profile.primary_measure_column
    aggregation = (
        _measure_aggregation(profile, primary_measure)
        if primary_measure
        else Aggregation.COUNT
    )
    for dimension in dimensions[:5]:
        segment = analyze_segment(
            query,
            dimension=dimension,
            measure=primary_measure,
            aggregation=aggregation,
        )
        if segment:
            segments.append(segment)
    if not dimensions:
        notes.append("No low-cardinality dimension was available for segmentation.")

    outliers = analyze_outliers(frame, profile)
    distributions = analyze_distributions(frame, profile)

    anomalies.sort(key=lambda a: -abs(a.z_score))

    result = AnalysisResult(
        dataset_id=profile.dataset_id,
        row_count=len(frame),
        correlations=correlations,
        trends=trends,
        segments=segments,
        outliers=outliers,
        anomalies=anomalies[:8],
        distributions=distributions,
        notes=notes,
    )
    log.info(
        "Analysis for %s: %d trends, %d segments, %d correlations, %d anomalies",
        profile.name, len(trends), len(segments), len(correlations), len(anomalies),
    )
    return result
