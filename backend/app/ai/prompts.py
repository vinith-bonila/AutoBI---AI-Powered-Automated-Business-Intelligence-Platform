"""Prompt construction for the two LLM steps.

Both prompts share one rule, stated as forcefully as possible: the model may
only reference values that appear in the JSON it is given. It never sees the
raw dataset, so it cannot invent a row; and every figure it cites is one the
Python layer already computed.
"""

from __future__ import annotations

import json
from typing import Any

from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import KPI
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport

SEMANTIC_SYSTEM = """\
You are a senior data analyst who designs business intelligence dashboards.

You will receive a JSON description of a dataset: its columns, their detected
types and semantic roles, and summary statistics. You will NOT receive the raw
rows.

Your job is to decide what this dataset is ABOUT and which metrics and charts
would matter to someone who owns this part of the business.

Hard rules:
- Reference ONLY column names that appear in the `fields` list. A name you
  invent will be discarded and the dashboard will be worse.
- Never state or estimate a metric VALUE. Values are computed separately in
  Python. You choose which metrics matter, not what they equal.
- Choose aggregations that make business sense: sum money and counts, average
  rates, prices and scores. Summing a unit price is always wrong.
- Prefer a few excellent KPIs over many mediocre ones.
- Respond with a single JSON object and nothing else.
"""

SEMANTIC_TEMPLATE = """\
Dataset file: {name}
Rows: {rows:,}   Columns: {columns}
Rule-based domain guess: {domain}
Detected domain signals: {signals}

Columns:
{fields}

The deterministic engine has already selected these KPIs:
{existing_kpis}

and these charts:
{existing_charts}

Produce a JSON object with this shape:

{{
  "domain": "<one of: sales, ecommerce, finance, hr, marketing, operations, customer, healthcare, education, general>",
  "dataset_title": "<a specific dashboard title, e.g. 'E-Commerce Revenue Performance'>",
  "dataset_description": "<1-2 sentences describing what this dataset captures and the period it covers>",
  "kpis": [
    {{
      "name": "<KPI name>",
      "measure_column": "<column to aggregate, or null if it is a ratio>",
      "aggregation": "<sum|avg|min|max|count|count_distinct|median>",
      "numerator_column": "<column, for ratio KPIs only>",
      "denominator_column": "<column, for ratio KPIs only>",
      "format": "<currency|number|percent|count|decimal>",
      "why_it_matters": "<one sentence on the business decision this informs>",
      "priority": <0-100>
    }}
  ],
  "charts": [
    {{
      "type": "<line|bar|horizontal_bar|area|pie|donut|scatter|histogram|heatmap|table>",
      "title": "<chart title>",
      "x": "<column>",
      "y": "<column or null>",
      "series": "<column to split by, or null>",
      "aggregation": "<sum|avg|count|...>",
      "columns": [],
      "rationale": "<why this view is worth a slot on the dashboard>"
    }}
  ]
}}

Suggest at most 6 KPIs and at most 4 charts. Suggest only charts that add
something the existing set does not already show.
"""

INSIGHT_SYSTEM = """\
You are a business analyst writing the insight section of a dashboard.

You will receive ONLY pre-computed statistics: KPI values, trend summaries,
segment rankings, correlations, detected anomalies and a data quality report.

Hard rules:
- Every number you write MUST appear in the input JSON. Do not round-trip a
  figure into a different unit, do not extrapolate, do not estimate.
- If you want to say something you cannot support with a number in the input,
  do not say it.
- Correlation is not causation. When you suggest a cause, mark it as a
  hypothesis ("may", "suggests", "consistent with").
- Write for a business reader: plain English, no statistics jargon, no
  restating column names verbatim when a natural phrase exists.
- Each insight cites the metrics it rests on in `evidence_refs`, using the
  exact metric labels from the input.
- Respond with a single JSON object and nothing else.
"""

INSIGHT_TEMPLATE = """\
Dataset: {title}
Domain: {domain}
Rows analysed: {rows:,}   Period: {period}

KPIs:
{kpis}

Computed evidence:
{evidence}

Data quality:
{quality}

Produce a JSON object:

{{
  "insights": [
    {{
      "title": "<a short, specific headline — not 'Revenue Analysis'>",
      "body": "<2-4 sentences: what is happening, and what may explain it>",
      "category": "<trend|anomaly|segment|correlation|distribution|quality|recommendation|summary>",
      "severity": "<positive|neutral|warning|critical>",
      "evidence_refs": ["<metric label from the input that supports this>"]
    }}
  ]
}}

Write between 4 and 6 insights covering, where the evidence supports it:
1. The headline movement in the data and its size.
2. The strongest and weakest segments.
3. Any anomaly or outlier that deserves attention.
4. A relationship between measures worth knowing about.
5. One concrete action a business owner might consider.

Order them most important first.
"""


def _compact_json(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, indent=2, default=str, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + "\n... (truncated)"
    return text


def build_semantic_prompt(
    profile: DatasetProfile,
    existing_kpis: list[str],
    existing_charts: list[str],
) -> str:
    compact = profile.compact()
    return SEMANTIC_TEMPLATE.format(
        name=profile.name,
        rows=profile.n_rows,
        columns=profile.n_columns,
        domain=profile.domain_guess or "general",
        signals="; ".join(profile.domain_signals) or "none",
        fields=_compact_json(compact["fields"]),
        existing_kpis="\n".join(f"- {k}" for k in existing_kpis) or "- (none)",
        existing_charts="\n".join(f"- {c}" for c in existing_charts) or "- (none)",
    )


def _period_label(profile: DatasetProfile) -> str:
    if not profile.primary_date_column:
        return "no date column"
    col = profile.column(profile.primary_date_column)
    if not col or not col.datetime or not col.datetime.min:
        return "unknown"
    return f"{col.datetime.min[:10]} to {(col.datetime.max or '')[:10]}"


def build_insight_prompt(
    profile: DatasetProfile,
    title: str,
    domain: str,
    kpis: list[KPI],
    analysis: AnalysisResult,
    quality: DataQualityReport,
) -> str:
    kpi_lines = []
    for kpi in kpis:
        line = f"- {kpi.name}: {kpi.formatted_value} (calculated as {kpi.calculation})"
        if kpi.comparison and kpi.comparison.change_pct is not None:
            line += (
                f" — {kpi.comparison.change_pct:+.1f}% "
                f"{kpi.comparison.period_label}"
            )
        kpi_lines.append(line)

    quality_summary = {
        "rows_after_cleaning": quality.rows_after,
        "rows_removed": quality.rows_removed,
        "duplicates_removed": quality.duplicates_removed,
        "quality_score": quality.quality_score,
        "columns_with_missing_values": [
            {"column": m.column, "missing_pct": m.missing_pct}
            for m in quality.missing_summary[:5]
        ],
        "warnings": quality.warnings[:4],
    }

    return INSIGHT_TEMPLATE.format(
        title=title,
        domain=domain,
        rows=analysis.row_count,
        period=_period_label(profile),
        kpis="\n".join(kpi_lines) or "- (none)",
        evidence=_compact_json(analysis.evidence_bundle()),
        quality=_compact_json(quality_summary, limit=1500),
    )
