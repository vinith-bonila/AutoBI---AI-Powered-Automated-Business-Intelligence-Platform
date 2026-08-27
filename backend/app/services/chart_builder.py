"""Ad-hoc chart construction and validation.

Chart switching, Add Visualization and time-grain changes all funnel through
here. The client sends a partial chart description; this module normalises it
into a `ChartSpecification`, validates it against the real dataset with the
SAME rules the recommender uses, and reports which chart types would be valid
for the chosen columns — so the UI can offer only sensible options.
"""

from __future__ import annotations

from typing import Any

from ..charts.validator import validate_chart
from ..config import Settings
from ..schemas.dashboard import ChartSpecification
from ..schemas.enums import (
    Aggregation,
    ChartType,
    InferredType,
    SemanticRole,
    TimeGrain,
)
from ..schemas.profile import DatasetProfile
from ..utils.formatting import humanize

# Chart types a user is allowed to pick, in menu order.
SWITCHABLE_TYPES: tuple[ChartType, ...] = (
    ChartType.BAR,
    ChartType.HORIZONTAL_BAR,
    ChartType.LINE,
    ChartType.AREA,
    ChartType.PIE,
    ChartType.DONUT,
    ChartType.SCATTER,
    ChartType.HISTOGRAM,
    ChartType.TABLE,
)


class ChartBuildError(ValueError):
    """Raised when an ad-hoc chart description is structurally invalid."""


def _grain(value: str | None) -> TimeGrain | None:
    if not value:
        return None
    try:
        return TimeGrain(value)
    except ValueError:
        return None


def build_chart(payload: dict[str, Any], profile: DatasetProfile) -> ChartSpecification:
    """Turn a loose client payload into a normalised `ChartSpecification`.

    Missing structural fields are filled with sensible defaults so the UI can
    send a minimal `{type, x, y, aggregation}` and get a complete spec back.
    """
    if not isinstance(payload, dict):
        raise ChartBuildError("Chart description must be an object.")

    type_value = str(payload.get("type", "")).strip()
    try:
        chart_type = ChartType(type_value)
    except ValueError as exc:
        raise ChartBuildError(f"Unknown chart type `{type_value}`.") from exc

    aggregation_value = str(payload.get("aggregation", "sum")).strip() or "sum"
    try:
        aggregation = Aggregation(aggregation_value)
    except ValueError:
        aggregation = Aggregation.SUM

    x = _clean(payload.get("x"))
    y = _clean(payload.get("y"))
    series = _clean(payload.get("series"))
    columns = [c for c in (payload.get("columns") or []) if _clean(c)]

    # Fill columns for table/heatmap from x/y when the client omitted them.
    if chart_type == ChartType.TABLE and not columns:
        columns = [c for c in (x, y, series) if c] or [
            col.name for col in profile.columns[:6]
        ]

    title = _clean(payload.get("title")) or _default_title(
        chart_type, x, y, series, aggregation, profile
    )
    grain = _grain(_clean(payload.get("time_grain")))
    if chart_type in (ChartType.LINE, ChartType.AREA) and grain is None and x:
        column = profile.column(x)
        if column and column.datetime and column.datetime.suggested_grain:
            grain = _grain(column.datetime.suggested_grain)

    chart_id = _clean(payload.get("id")) or _slug(chart_type, x, y, series)

    try:
        return ChartSpecification(
            id=chart_id,
            type=chart_type,
            title=title,
            description=_clean(payload.get("description")),
            x=x,
            y=y,
            series=series,
            aggregation=aggregation,
            time_grain=grain,
            sort=_clean(payload.get("sort")) or "value_desc",
            limit=payload.get("limit"),
            bins=payload.get("bins"),
            columns=columns,
            section=_clean(payload.get("section")) or "secondary",
            width=_clean(payload.get("width")) or "half",
            rationale=_clean(payload.get("rationale")),
        )
    except ValueError as exc:
        # Pydantic's structural rules (e.g. "line needs x and y") land here.
        raise ChartBuildError(str(exc)) from exc


def build_and_validate(
    payload: dict[str, Any],
    profile: DatasetProfile,
    *,
    settings: Settings,
    available: set[str],
) -> ChartSpecification:
    """Build a chart and run it through the deterministic validator."""
    chart = build_chart(payload, profile)
    result = validate_chart(
        chart, profile, settings=settings, available_columns=available
    )
    if not result.ok:
        raise ChartBuildError(result.reason or "This chart is not valid for the data.")
    return chart


def allowed_types_for(
    *,
    x: str | None,
    y: str | None,
    profile: DatasetProfile,
    settings: Settings,
    available: set[str],
) -> list[str]:
    """Which chart types are valid for the given axis columns.

    Used to populate the "change chart type" menu with only sensible options.
    Each candidate is built and validated exactly as it would be if the user
    picked it, so the menu can never offer a type that would then fail.
    """
    valid: list[str] = []
    for chart_type in SWITCHABLE_TYPES:
        payload: dict[str, Any] = {
            "type": chart_type.value,
            "x": x,
            "y": y,
            "aggregation": _default_aggregation(chart_type, y, profile),
        }
        if chart_type in (ChartType.HISTOGRAM,):
            payload["aggregation"] = "count"
            payload["x"] = x if _is_numeric(x, profile) else y
        if chart_type == ChartType.TABLE:
            payload["columns"] = [c for c in (x, y) if c]
        try:
            chart = build_chart(payload, profile)
        except ChartBuildError:
            continue
        if validate_chart(
            chart, profile, settings=settings, available_columns=available
        ).ok:
            valid.append(chart_type.value)
    return valid


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_numeric(name: str | None, profile: DatasetProfile) -> bool:
    if not name:
        return False
    column = profile.column(name)
    return bool(column and column.inferred_type == InferredType.NUMERIC)


def _default_aggregation(
    chart_type: ChartType, y: str | None, profile: DatasetProfile
) -> str:
    if chart_type in (ChartType.HISTOGRAM,):
        return "count"
    if chart_type == ChartType.SCATTER:
        return "none"
    if not y:
        return "count"
    column = profile.column(y)
    if column and column.semantic_role in (
        SemanticRole.PERCENTAGE,
        SemanticRole.RATIO,
        SemanticRole.DEMOGRAPHIC,
    ):
        return "avg"
    return "sum"


def _default_title(
    chart_type: ChartType,
    x: str | None,
    y: str | None,
    series: str | None,
    aggregation: Aggregation,
    profile: DatasetProfile,
) -> str:
    agg_word = {
        Aggregation.SUM: "Total",
        Aggregation.AVG: "Average",
        Aggregation.COUNT: "Count of",
        Aggregation.MEDIAN: "Median",
        Aggregation.MIN: "Min",
        Aggregation.MAX: "Max",
        Aggregation.COUNT_DISTINCT: "Distinct",
    }.get(aggregation, "")

    if chart_type == ChartType.HISTOGRAM and x:
        return f"Distribution of {humanize(x)}"
    if chart_type == ChartType.SCATTER and x and y:
        return f"{humanize(x)} vs {humanize(y)}"
    if chart_type in (ChartType.LINE, ChartType.AREA) and y:
        return f"{humanize(y)} Over Time"
    if chart_type == ChartType.TABLE:
        return "Data Table"
    if x and y:
        measure = humanize(y)
        return f"{agg_word} {measure} by {humanize(x)}".strip()
    if x:
        return f"Records by {humanize(x)}"
    return "Chart"


def _slug(
    chart_type: ChartType, x: str | None, y: str | None, series: str | None
) -> str:
    parts = [chart_type.value, x or "", y or "", series or ""]
    base = "_".join(p for p in parts if p)
    return f"custom_{base}"[:60].lower().replace(" ", "_")
