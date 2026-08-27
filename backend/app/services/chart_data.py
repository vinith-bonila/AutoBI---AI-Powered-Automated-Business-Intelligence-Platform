"""Executing a chart specification against the dataset.

Filters arrive from the browser on every interaction, so this is the hottest
path in the product and the one most exposed to untrusted input. It resolves a
chart *by id* from the stored specification — the client never describes a
query, it names one that the backend already validated — and passes the filter
values through `DatasetQuery`, which binds them as SQL parameters.
"""

from __future__ import annotations

import pandas as pd

from ..analysis.query import DatasetQuery, QueryError
from ..config import Settings
from ..schemas.api import ChartDataResponse, FilterValue
from ..schemas.dashboard import ChartSpecification
from ..schemas.enums import Aggregation, ChartType, TimeGrain
from ..utils.formatting import humanize
from ..utils.logging import get_logger
from ..utils.serialization import records, to_native

log = get_logger(__name__)


def _period_label(value: object, grain: TimeGrain) -> str:
    timestamp = pd.Timestamp(value)
    if grain == TimeGrain.YEAR:
        return timestamp.strftime("%Y")
    if grain == TimeGrain.QUARTER:
        return f"{timestamp.year} Q{((timestamp.month - 1) // 3) + 1}"
    if grain == TimeGrain.MONTH:
        return timestamp.strftime("%b %Y")
    if grain == TimeGrain.WEEK:
        return timestamp.strftime("%d %b %Y")
    return timestamp.strftime("%d %b %Y")


def _measure_key(chart: ChartSpecification) -> str:
    if chart.aggregation in (Aggregation.COUNT, Aggregation.COUNT_DISTINCT) and not chart.y:
        return "Records"
    return humanize(chart.y) if chart.y else "Value"


def execute_chart(
    chart: ChartSpecification,
    query: DatasetQuery,
    *,
    filters: list[FilterValue],
    settings: Settings,
) -> ChartDataResponse:
    """Run one chart and shape the result for the frontend renderer."""
    measure_key = _measure_key(chart)

    def empty(reason: str) -> ChartDataResponse:
        return ChartDataResponse(
            chart_id=chart.id,
            type=chart.type.value,
            x_key="x",
            y_keys=[measure_key],
            data=[],
            row_count=0,
            empty_reason=reason,
        )

    try:
        # -- time series ---------------------------------------------------
        if chart.type in (ChartType.LINE, ChartType.AREA):
            grain = chart.time_grain or TimeGrain.MONTH
            frame = query.time_series(
                chart.x,
                chart.y,
                chart.aggregation,
                grain,
                filters=filters,
                series=chart.series,
            )
            if frame.empty:
                return empty("No rows match the current filters.")

            if chart.series:
                pivot = frame.pivot_table(
                    index="period", columns="series", values="value", aggfunc="sum"
                ).sort_index()
                series_keys = [str(c) for c in pivot.columns]
                data = []
                for period, row in pivot.iterrows():
                    point = {"x": _period_label(period, grain)}
                    for key in series_keys:
                        point[key] = to_native(row[key])
                    data.append(point)
                return ChartDataResponse(
                    chart_id=chart.id,
                    type=chart.type.value,
                    x_key="x",
                    y_keys=series_keys,
                    data=data,
                    row_count=len(data),
                )

            data = [
                {
                    "x": _period_label(row.period, grain),
                    measure_key: to_native(row.value),
                }
                for row in frame.itertuples()
            ]
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key="x",
                y_keys=[measure_key],
                data=data,
                row_count=len(data),
            )

        # -- categorical ---------------------------------------------------
        if chart.type in (
            ChartType.BAR,
            ChartType.HORIZONTAL_BAR,
            ChartType.PIE,
            ChartType.DONUT,
        ):
            limit = chart.limit or settings.max_chart_categories
            if chart.series:
                frame = query.aggregate_by_dimension_series(
                    chart.x,
                    chart.series,
                    chart.y,
                    chart.aggregation,
                    filters=filters,
                    limit=limit,
                )
                if frame.empty:
                    return empty("No rows match the current filters.")
                pivot = frame.pivot_table(
                    index="label", columns="series", values="value", aggfunc="sum"
                )
                series_keys = [str(c) for c in pivot.columns]
                pivot = pivot.reindex(
                    pivot.sum(axis=1).sort_values(ascending=False).index
                ).head(limit)
                data = []
                for label, row in pivot.iterrows():
                    point = {"x": str(label)}
                    for key in series_keys:
                        point[key] = to_native(row[key])
                    data.append(point)
                return ChartDataResponse(
                    chart_id=chart.id,
                    type=chart.type.value,
                    x_key="x",
                    y_keys=series_keys,
                    data=data,
                    row_count=len(data),
                )

            frame = query.aggregate_by_dimension(
                chart.x,
                chart.y,
                chart.aggregation,
                filters=filters,
                limit=limit,
                sort=chart.sort or "value_desc",
            )
            if frame.empty:
                return empty("No rows match the current filters.")

            total = float(pd.to_numeric(frame["value"], errors="coerce").abs().sum())
            data = []
            for row in frame.itertuples():
                value = to_native(row.value)
                point = {
                    "x": str(row.label),
                    measure_key: value,
                    "rows": int(getattr(row, "row_count", 0) or 0),
                }
                if total and isinstance(value, (int, float)):
                    point["share"] = round(abs(value) / total * 100, 2)
                data.append(point)
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key="x",
                y_keys=[measure_key],
                data=data,
                row_count=len(data),
                truncated=len(data) >= limit,
            )

        # -- scatter -------------------------------------------------------
        if chart.type == ChartType.SCATTER:
            frame = query.scatter(
                chart.x,
                chart.y,
                filters=filters,
                series=chart.series,
                limit=chart.limit or settings.max_chart_points,
            )
            if frame.empty:
                return empty("No rows match the current filters.")
            data = records(frame)
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key="x",
                y_keys=["y"],
                data=data,
                row_count=len(data),
                truncated=len(data) >= (chart.limit or settings.max_chart_points),
            )

        # -- histogram -----------------------------------------------------
        if chart.type == ChartType.HISTOGRAM:
            frame = query.histogram(
                chart.x, bins=chart.bins or 20, filters=filters
            )
            if frame.empty:
                return empty("No numeric values match the current filters.")
            data = [
                {
                    "x": str(row.label),
                    "Count": int(row.count),
                    "bin_start": to_native(row.bin_start),
                    "bin_end": to_native(row.bin_end),
                }
                for row in frame.itertuples()
            ]
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key="x",
                y_keys=["Count"],
                data=data,
                row_count=len(data),
            )

        # -- heatmap -------------------------------------------------------
        if chart.type == ChartType.HEATMAP:
            frame = query.correlation_matrix(chart.columns, filters=filters)
            if frame.empty:
                return empty("Not enough numeric data for a correlation matrix.")
            data = [
                {
                    "x": humanize(str(row.x)),
                    "y": humanize(str(row.y)),
                    "value": to_native(row.value),
                    "x_column": str(row.x),
                    "y_column": str(row.y),
                }
                for row in frame.itertuples()
            ]
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key="x",
                y_keys=["value"],
                data=data,
                row_count=len(data),
            )

        # -- table ---------------------------------------------------------
        if chart.type == ChartType.TABLE:
            limit = min(chart.limit or 100, settings.max_table_rows)
            frame = query.table(
                chart.columns,
                filters=filters,
                limit=limit,
                order_by=chart.y if chart.y in chart.columns else None,
            )
            if frame.empty:
                return empty("No rows match the current filters.")
            return ChartDataResponse(
                chart_id=chart.id,
                type=chart.type.value,
                x_key=chart.columns[0],
                y_keys=list(chart.columns),
                data=records(frame),
                row_count=len(frame),
                truncated=len(frame) >= limit,
            )

    except QueryError as exc:
        log.warning("Chart %s failed: %s", chart.id, exc)
        return empty(str(exc))

    return empty(f"Unsupported chart type `{chart.type.value}`.")
