"""Export builders.

Each function returns bytes plus a filename and media type, ready to stream.
Excel uses pandas' built-in writer; everything else is stdlib. Nothing here
depends on the frontend — PDF/PNG of the live dashboard are produced client-
side, while these are the data-level exports.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import DashboardSpecification
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport
from ..utils.formatting import humanize
from . import semantic_model


@dataclass
class ExportFile:
    content: bytes
    filename: str
    media_type: str


def cleaned_csv(frame: pd.DataFrame, *, stem: str) -> ExportFile:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return ExportFile(
        content=buffer.getvalue().encode("utf-8-sig"),
        filename=f"{stem}_cleaned.csv",
        media_type="text/csv",
    )


def data_dictionary_csv(profile: DatasetProfile, *, stem: str) -> ExportFile:
    rows = semantic_model.build_data_dictionary(profile)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return ExportFile(
        content=buffer.getvalue().encode("utf-8-sig"),
        filename=f"{stem}_data_dictionary.csv",
        media_type="text/csv",
    )


def semantic_model_json(
    profile: DatasetProfile,
    spec: DashboardSpecification,
    *,
    filename: str,
    stem: str,
) -> ExportFile:
    model = semantic_model.build_semantic_model(profile, spec, filename=filename)
    return ExportFile(
        content=json.dumps(model, indent=2, default=str).encode("utf-8"),
        filename=f"{stem}_semantic_model.json",
        media_type="application/json",
    )


def dashboard_config_json(
    spec: DashboardSpecification,
    profile: DatasetProfile,
    *,
    filename: str,
    stem: str,
    client_config: dict[str, Any] | None = None,
) -> ExportFile:
    """The reloadable dashboard configuration.

    Combines the server spec (KPIs, charts, filters) with the client's
    customisation (theme, palette, layout, time grain, ordering) when provided.
    """
    payload = {
        "format": "autobi.dashboard-config",
        "format_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "filename": filename,
            "name": spec.title,
            "domain": spec.domain,
            "rows": profile.n_rows,
            "columns": profile.n_columns,
            "primary_date_column": profile.primary_date_column,
            "primary_measure_column": profile.primary_measure_column,
        },
        "presentation": client_config
        or {
            "theme": "professional",
            "palette": "corporate",
            "layout": "two-column",
            "time_grain": (
                spec.charts[0].time_grain.value
                if spec.charts and spec.charts[0].time_grain
                else None
            ),
        },
        "kpis": [kpi.model_dump(mode="json") for kpi in spec.kpis],
        "charts": [chart.model_dump(mode="json") for chart in spec.charts],
        "filters": [f.model_dump(mode="json") for f in spec.filters],
        "insights": [i.model_dump(mode="json") for i in spec.insights],
    }
    return ExportFile(
        content=json.dumps(payload, indent=2, default=str).encode("utf-8"),
        filename=f"{stem}_dashboard_config.json",
        media_type="application/json",
    )


def analysis_report_markdown(
    spec: DashboardSpecification,
    profile: DatasetProfile,
    quality: DataQualityReport,
    analysis: AnalysisResult,
    *,
    stem: str,
) -> ExportFile:
    """A shareable written report of the whole analysis."""
    lines: list[str] = []
    add = lines.append

    add(f"# {spec.title}")
    add("")
    add(f"_{spec.description}_")
    add("")
    add(
        f"**Domain:** {humanize(spec.domain)} · **Rows:** {profile.n_rows:,} · "
        f"**Columns:** {profile.n_columns} · "
        f"**Data quality:** {quality.quality_score:.0f}/100"
    )
    add("")

    add("## Key metrics")
    add("")
    for kpi in spec.kpis:
        delta = ""
        if kpi.comparison and kpi.comparison.change_pct is not None:
            delta = f" ({kpi.comparison.change_pct:+.1f}% {kpi.comparison.period_label})"
        add(f"- **{kpi.name}:** {kpi.formatted_value}{delta} — {kpi.why_it_matters}")
    add("")

    if analysis.trends:
        add("## Trends")
        add("")
        for trend in analysis.trends:
            change = (
                f"{trend.change_pct:+.1f}%" if trend.change_pct is not None else "n/a"
            )
            add(
                f"- **{humanize(trend.measure)}** changed {change} "
                f"({trend.direction}) over the period, by {trend.grain}."
            )
        add("")

    if analysis.segments:
        add("## Segment breakdown")
        add("")
        for seg in analysis.segments[:4]:
            if not seg.top:
                continue
            leader = seg.top[0]
            add(
                f"- **By {humanize(seg.dimension)}:** {leader.label} leads with "
                f"{leader.share_pct:.1f}% of {humanize(seg.measure)}; "
                f"top 3 hold {seg.concentration_pct:.0f}%."
                if seg.concentration_pct is not None
                else f"- **By {humanize(seg.dimension)}:** {leader.label} leads."
            )
        add("")

    add("## Insights")
    add("")
    for insight in spec.insights:
        add(f"### {insight.title}")
        add("")
        add(insight.body)
        if insight.evidence:
            add("")
            for ev in insight.evidence:
                add(f"- {ev.metric}: **{ev.value}**")
        add("")

    add("## Data quality")
    add("")
    add(
        f"- Rows: {quality.rows_before:,} → {quality.rows_after:,} "
        f"({quality.duplicates_removed:,} duplicates removed)"
    )
    add(f"- Completeness {quality.completeness_score:.0f} · "
        f"Uniqueness {quality.uniqueness_score:.0f} · "
        f"Consistency {quality.consistency_score:.0f}")
    add("")
    add("### Cleaning actions")
    add("")
    for action in quality.actions:
        target = f" `{action.column}`" if action.column else ""
        add(f"- {action.action.value}{target}: {action.reason} "
            f"({action.rows_affected:,} rows)")
    add("")
    add("---")
    add(f"_Generated by AutoBI on {datetime.now().strftime('%Y-%m-%d %H:%M')}._")

    return ExportFile(
        content="\n".join(lines).encode("utf-8"),
        filename=f"{stem}_report.md",
        media_type="text/markdown",
    )


def excel_workbook(
    frame: pd.DataFrame,
    spec: DashboardSpecification,
    profile: DatasetProfile,
    analysis: AnalysisResult,
    *,
    stem: str,
) -> ExportFile:
    """A multi-sheet workbook: KPIs, cleaned data, dictionary, segments."""
    buffer = io.BytesIO()
    engine = _excel_engine()

    with pd.ExcelWriter(buffer, engine=engine) as writer:
        # KPIs
        kpi_rows = [
            {
                "KPI": kpi.name,
                "Value": kpi.value,
                "Formatted": kpi.formatted_value,
                "Change %": kpi.comparison.change_pct if kpi.comparison else None,
                "Calculation": kpi.calculation,
                "Why it matters": kpi.why_it_matters,
            }
            for kpi in spec.kpis
        ]
        pd.DataFrame(kpi_rows).to_excel(writer, sheet_name="KPIs", index=False)

        # Segments
        seg_rows = []
        for seg in analysis.segments:
            for row in seg.top:
                seg_rows.append(
                    {
                        "Dimension": humanize(seg.dimension),
                        "Category": row.label,
                        "Measure": humanize(seg.measure),
                        "Value": row.value,
                        "Share %": row.share_pct,
                    }
                )
        if seg_rows:
            pd.DataFrame(seg_rows).to_excel(
                writer, sheet_name="Segments", index=False
            )

        # Data dictionary
        pd.DataFrame(semantic_model.build_data_dictionary(profile)).to_excel(
            writer, sheet_name="Data Dictionary", index=False
        )

        # Cleaned data (capped so the file stays openable)
        frame.head(100_000).to_excel(writer, sheet_name="Cleaned Data", index=False)

    return ExportFile(
        content=buffer.getvalue(),
        filename=f"{stem}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _excel_engine() -> str:
    """Pick whichever Excel writer is installed."""
    try:
        import openpyxl  # noqa: F401

        return "openpyxl"
    except ImportError:  # pragma: no cover
        try:
            import xlsxwriter  # noqa: F401

            return "xlsxwriter"
        except ImportError as exc:
            raise RuntimeError(
                "No Excel writer is installed. Add `openpyxl` to requirements."
            ) from exc
