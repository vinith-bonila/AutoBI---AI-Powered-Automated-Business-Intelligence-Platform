"""Semantic model — the export abstraction that Power BI integration will build on.

Rather than fake a `.pbix`, AutoBI exposes a clean, tool-agnostic description of
the dataset's *meaning*: tables, columns (with data categories and format
strings), measures (as expressions), and the dashboard's visuals. This is the
layer a real Power BI / Tabular exporter would consume later; today it powers
the JSON exports and the data dictionary.

The shape deliberately mirrors concepts common to BI semantic layers (Power BI
Tabular, dbt metrics, Looker) so a future `PowerBIExporter` can map field-by-
field without touching the rest of the system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas.dashboard import DashboardSpecification
from ..schemas.enums import SemanticRole
from ..schemas.profile import DatasetProfile
from ..utils.formatting import humanize

# Map our semantic roles to Power-BI-style "data categories" / summarisation.
_DATA_CATEGORY = {
    SemanticRole.CURRENCY: "Currency",
    SemanticRole.PERCENTAGE: "Percentage",
    SemanticRole.GEO: "Place",
    SemanticRole.TIME: "DateTime",
    SemanticRole.IDENTIFIER: "Uncategorized",
}

_FORMAT_STRING = {
    SemanticRole.CURRENCY: '"$"#,0.00',
    SemanticRole.PERCENTAGE: "0.0%",
    SemanticRole.QUANTITY: "#,0",
}

_TABULAR_TYPE = {
    "numeric": "double",
    "datetime": "dateTime",
    "boolean": "boolean",
    "categorical": "string",
    "text": "string",
    "empty": "string",
}


def build_semantic_model(
    profile: DatasetProfile,
    spec: DashboardSpecification,
    *,
    filename: str,
) -> dict[str, Any]:
    """A BI-tool-agnostic semantic description of the dataset and dashboard."""
    columns = []
    for col in profile.columns:
        columns.append(
            {
                "name": col.name,
                "display_name": humanize(col.name),
                "data_type": _TABULAR_TYPE.get(col.inferred_type.value, "string"),
                "semantic_role": col.semantic_role.value,
                "data_category": _DATA_CATEGORY.get(col.semantic_role, "Uncategorized"),
                "format_string": _FORMAT_STRING.get(col.semantic_role),
                "summarize_by": (
                    "sum" if col.name in profile.measure_columns else "none"
                ),
                "is_key": col.is_unique_key,
                "is_hidden": col.semantic_role == SemanticRole.IDENTIFIER
                and col.is_unique_key,
                "missing_pct": col.missing_pct,
                "unique_values": col.unique,
                "description": col.role_evidence[0] if col.role_evidence else None,
            }
        )

    # KPIs become measures, expressed portably (a DAX/SQL exporter maps these).
    measures = []
    for kpi in spec.kpis:
        measures.append(
            {
                "name": kpi.name,
                "identifier": kpi.id,
                "expression": kpi.calculation,
                "format": kpi.format.value,
                "description": kpi.why_it_matters,
                "source_columns": kpi.source_columns,
            }
        )

    visuals = []
    for chart in spec.charts:
        visuals.append(
            {
                "id": chart.id,
                "visual_type": _powerbi_visual(chart.type.value),
                "native_type": chart.type.value,
                "title": chart.title,
                "category_axis": chart.x,
                "value_axis": chart.y,
                "series": chart.series,
                "aggregation": chart.aggregation.value,
                "time_grain": chart.time_grain.value if chart.time_grain else None,
                "columns": chart.columns,
            }
        )

    return {
        "format": "autobi.semantic-model",
        "format_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"filename": filename, "row_count": profile.n_rows},
        "model": {
            "name": humanize(filename.replace(".csv", "")),
            "domain": spec.domain,
            "tables": [
                {
                    "name": "data",
                    "row_count": profile.n_rows,
                    "columns": columns,
                }
            ],
            "measures": measures,
            "relationships": [],  # single-table MVP; the field exists for later
        },
        "report": {
            "title": spec.title,
            "description": spec.description,
            "filters": [
                {"column": f.column, "type": f.kind.value} for f in spec.filters
            ],
            "visuals": visuals,
        },
        "powerbi_readiness": {
            "note": (
                "This is a tool-agnostic semantic model. A future PowerBIExporter "
                "maps `measures[].expression` to DAX and `visuals[]` to report "
                "layout. No .pbix is fabricated here."
            ),
            "supported": True,
        },
    }


def build_data_dictionary(profile: DatasetProfile) -> list[dict[str, Any]]:
    """A human-readable data dictionary, one row per column."""
    rows = []
    for col in profile.columns:
        rows.append(
            {
                "column": col.name,
                "display_name": humanize(col.name),
                "type": col.inferred_type.value,
                "role": col.semantic_role.value,
                "role_confidence": col.role_confidence,
                "role_evidence": "; ".join(col.role_evidence),
                "missing_pct": col.missing_pct,
                "unique_values": col.unique,
                "is_measure": col.name in profile.measure_columns,
                "is_dimension": col.name in profile.dimension_columns,
                "example_values": ", ".join(col.sample_values[:3]),
            }
        )
    return rows


def _powerbi_visual(chart_type: str) -> str:
    """Map our chart type to the nearest Power BI visual name."""
    return {
        "line": "lineChart",
        "area": "areaChart",
        "bar": "columnChart",
        "horizontal_bar": "barChart",
        "pie": "pieChart",
        "donut": "donutChart",
        "scatter": "scatterChart",
        "histogram": "columnChart",
        "heatmap": "matrix",
        "table": "tableEx",
    }.get(chart_type, "columnChart")


class ExportTarget:
    """Interface for a future integration target (Power BI, Tableau, …).

    Implement `export(semantic_model) -> bytes` to add a new destination. The
    MVP ships only the JSON semantic model; this seam keeps that extension from
    touching the rest of the codebase.
    """

    name = "base"

    def export(self, semantic_model: dict[str, Any]) -> bytes:  # pragma: no cover
        raise NotImplementedError
