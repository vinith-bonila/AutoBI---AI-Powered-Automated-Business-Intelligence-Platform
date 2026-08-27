"""Deterministic validation of chart specifications.

This is the gate between "something proposed a chart" and "the dashboard
renders it". It answers one question per chart: *given the real columns and
their real types, does this chart make sense?*

The rules are intentionally strict. A rejected chart is dropped and replaced
by a deterministic alternative, which is always better than rendering a pie
chart of 4,000 customer ids.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..schemas.dashboard import ChartSpecification
from ..schemas.enums import (
    Aggregation,
    ChartType,
    InferredType,
    SemanticRole,
)
from ..schemas.profile import ColumnProfile, DatasetProfile

# A pie/donut with more slices than this is unreadable.
MAX_PIE_SLICES = 8
MIN_PIE_SLICES = 2
MIN_SCATTER_ROWS = 20
MIN_HISTOGRAM_UNIQUE = 5


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


VALID = ValidationResult(True)


def _reject(reason: str) -> ValidationResult:
    return ValidationResult(False, reason)


def _numeric(col: ColumnProfile | None) -> bool:
    return col is not None and col.inferred_type == InferredType.NUMERIC


def _groupable(col: ColumnProfile | None) -> bool:
    return col is not None and col.inferred_type in (
        InferredType.CATEGORICAL,
        InferredType.BOOLEAN,
    )


def validate_chart(
    chart: ChartSpecification,
    profile: DatasetProfile,
    *,
    settings: Settings,
    available_columns: set[str] | None = None,
) -> ValidationResult:
    """Check one chart against the dataset it will be rendered from."""
    available = available_columns or {c.name for c in profile.columns}

    # -- every referenced column must exist --------------------------------
    referenced = [c for c in (chart.x, chart.y, chart.series) if c] + list(chart.columns)
    for name in referenced:
        if name not in available:
            return _reject(f"Column `{name}` does not exist in the dataset.")

    x = profile.column(chart.x) if chart.x else None
    y = profile.column(chart.y) if chart.y else None
    series = profile.column(chart.series) if chart.series else None

    # A measure must be numeric unless we are simply counting rows.
    counting = chart.aggregation in (Aggregation.COUNT, Aggregation.COUNT_DISTINCT)
    if y is not None and not counting and not _numeric(y):
        return _reject(f"`{chart.y}` is not numeric, so it cannot be aggregated.")

    if series is not None:
        if not _groupable(series):
            return _reject(f"`{chart.series}` cannot be used to split the series.")
        if series.unique > 12:
            return _reject(
                f"`{chart.series}` has {series.unique} values — too many to split by."
            )

    # -- per-type rules ----------------------------------------------------
    if chart.type in (ChartType.LINE, ChartType.AREA):
        if x is None or x.inferred_type != InferredType.DATETIME:
            return _reject(
                f"A {chart.type.value} chart needs a date on the x axis; "
                f"`{chart.x}` is {x.inferred_type.value if x else 'missing'}."
            )
        if y is None and not counting:
            return _reject("A time-series chart needs a measure.")
        if x.count < 3:
            return _reject("Not enough dated rows to draw a trend.")
        return VALID

    if chart.type in (ChartType.BAR, ChartType.HORIZONTAL_BAR):
        if not _groupable(x):
            return _reject(
                f"`{chart.x}` is not a grouping dimension "
                f"({x.inferred_type.value if x else 'missing'})."
            )
        if x.semantic_role == SemanticRole.IDENTIFIER:
            return _reject(f"`{chart.x}` identifies rows, so grouping by it is noise.")
        if x.is_constant:
            return _reject(f"`{chart.x}` has only one value.")
        if x.unique > settings.max_categorical_cardinality:
            return _reject(
                f"`{chart.x}` has {x.unique} categories — beyond the readable limit."
            )
        return VALID

    if chart.type in (ChartType.PIE, ChartType.DONUT):
        if not _groupable(x):
            return _reject(f"`{chart.x}` is not a category, so it has no parts to show.")
        if x.semantic_role == SemanticRole.IDENTIFIER:
            return _reject(f"`{chart.x}` identifies rows and cannot form a share chart.")
        if not (MIN_PIE_SLICES <= x.unique <= MAX_PIE_SLICES):
            return _reject(
                f"`{chart.x}` has {x.unique} categories; a share chart is only "
                f"readable between {MIN_PIE_SLICES} and {MAX_PIE_SLICES}."
            )
        # Parts-of-a-whole is meaningless when the parts can be negative.
        if y is not None and y.numeric and (y.numeric.negative_pct or 0) > 0:
            return _reject(
                f"`{chart.y}` contains negative values, which cannot form a "
                "share of a total."
            )
        # Averages do not add up to the whole, so they cannot be sliced.
        if chart.aggregation not in (Aggregation.SUM, Aggregation.COUNT):
            return _reject(
                f"A share chart needs an additive aggregation; "
                f"`{chart.aggregation.value}` values do not sum to a total."
            )
        return VALID

    if chart.type == ChartType.SCATTER:
        if not _numeric(x) or not _numeric(y):
            return _reject("A scatter plot needs two numeric columns.")
        if x.semantic_role == SemanticRole.IDENTIFIER or y.semantic_role == SemanticRole.IDENTIFIER:
            return _reject("Identifier columns carry no relationship to plot.")
        if chart.x == chart.y:
            return _reject("A scatter plot needs two different columns.")
        if profile.n_rows < MIN_SCATTER_ROWS:
            return _reject("Too few rows for a meaningful scatter plot.")
        return VALID

    if chart.type == ChartType.HISTOGRAM:
        if not _numeric(x):
            return _reject(f"`{chart.x}` is not numeric, so it cannot be binned.")
        if x.semantic_role == SemanticRole.IDENTIFIER:
            return _reject(f"`{chart.x}` identifies rows; its distribution is flat.")
        if x.unique < MIN_HISTOGRAM_UNIQUE:
            return _reject(
                f"`{chart.x}` has only {x.unique} distinct values — a bar chart "
                "describes it better than a histogram."
            )
        return VALID

    if chart.type == ChartType.HEATMAP:
        numeric_columns = [
            c for c in chart.columns
            if _numeric(profile.column(c))
            and profile.column(c).semantic_role != SemanticRole.IDENTIFIER
        ]
        if len(numeric_columns) < 2:
            return _reject("A correlation heatmap needs at least two numeric columns.")
        return VALID

    if chart.type == ChartType.TABLE:
        if not chart.columns:
            return _reject("A table needs at least one column.")
        return VALID

    return _reject(f"Unsupported chart type `{chart.type}`.")


def validate_charts(
    charts: list[ChartSpecification],
    profile: DatasetProfile,
    *,
    settings: Settings,
    available_columns: set[str] | None = None,
) -> tuple[list[ChartSpecification], list[str]]:
    """Filter a list of charts, returning the survivors and rejection notes."""
    kept: list[ChartSpecification] = []
    notes: list[str] = []
    seen: set[tuple] = set()

    for chart in charts:
        result = validate_chart(
            chart, profile, settings=settings, available_columns=available_columns
        )
        if not result.ok:
            notes.append(f"Dropped `{chart.title}`: {result.reason}")
            continue
        # Collapse charts that would render identically.
        signature = (
            chart.type,
            chart.x,
            chart.y,
            chart.series,
            chart.aggregation,
            tuple(chart.columns),
        )
        if signature in seen:
            notes.append(f"Dropped `{chart.title}`: duplicates another chart.")
            continue
        seen.add(signature)
        kept.append(chart)

    return kept, notes
