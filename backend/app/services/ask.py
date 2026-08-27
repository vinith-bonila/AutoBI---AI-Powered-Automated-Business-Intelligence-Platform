"""Ask Your Data — grounded natural-language Q&A over a dataset.

The invariant is the same one that governs the whole product: the LLM never
produces a number. The flow is:

    question
      → plan   (LLM maps the question to a structured query plan; a keyword
                planner is the fallback and the seed)
      → validate the plan against the REAL columns
      → execute deterministically (DuckDB)   ← the numbers are born here
      → explain (LLM narrates the computed result; a template is the fallback)

So a hallucinated column is rejected at the validate step, and the figures in
the answer are exactly the ones Python computed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..ai.client import AIService
from ..analysis.query import DatasetQuery, QueryError
from ..config import Settings
from ..schemas.api import AskChart, AskEvidence, AskResponse, FilterValue
from ..schemas.dashboard import ChartSpecification, LLMAskExplanation, LLMAskPlan
from ..schemas.enums import Aggregation, ChartType, InferredType, SemanticRole, TimeGrain
from ..schemas.profile import DatasetProfile
from ..utils.formatting import format_value, humanize
from ..utils.logging import get_logger
from ..utils.serialization import records, to_native
from . import chart_builder
from .chart_data import execute_chart

log = get_logger(__name__)

PLAN_SYSTEM = """\
You convert a business question about a dataset into a structured query plan.
You are given the dataset's columns with their types and roles. You do NOT see
the data and you never compute or guess a value.

Rules:
- Use ONLY column names from the provided list.
- Pick the single most relevant measure and dimension for the question.
- `intent` is one of: rank (top/bottom by a dimension), trend (over time),
  distribution (spread of one measure), aggregate (a single total/average),
  table (list rows), compare (two periods or groups).
- Choose an aggregation that fits the measure (sum money/counts, avg rates).
- Respond with a single JSON object, nothing else.
"""

PLAN_TEMPLATE = """\
Dataset: {name} ({rows} rows)
Columns:
{fields}

Primary date column: {date_col}
Primary measure: {measure_col}

Question: "{question}"

Return JSON:
{{
  "intent": "rank|trend|distribution|aggregate|table|compare",
  "measure_column": "<column or null>",
  "aggregation": "sum|avg|min|max|count|count_distinct|median",
  "dimension_column": "<column or null>",
  "date_column": "<column or null>",
  "time_grain": "day|week|month|quarter|year or null",
  "limit": 10,
  "sort": "value_desc|value_asc",
  "filter_column": "<column or null>",
  "filter_value": "<value or null>",
  "needs_clarification": false
}}
"""

EXPLAIN_SYSTEM = """\
You explain a pre-computed analytical result to a business user in 1-3 clear
sentences. You are given the question and the ACTUAL computed numbers.

Rules:
- Use ONLY the numbers provided. Never invent, round differently, or add
  figures that are not in the input.
- Be specific and direct. Lead with the answer.
- No preamble like "Based on the data". Just answer.
- Respond with a single JSON object: {"answer": "..."}.
"""

EXPLAIN_TEMPLATE = """\
Question: "{question}"

Computed result:
{result}

Write the answer as JSON: {{"answer": "..."}}.
"""


@dataclass
class ExecutedPlan:
    intent: str
    headline: str | None
    evidence: list[AskEvidence]
    table: pd.DataFrame
    chart: ChartSpecification | None
    summary_for_llm: dict[str, Any]
    interpretation: str
    warning: str | None = None
    facts: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# keyword planner (deterministic fallback + seed)
# --------------------------------------------------------------------------

_TOP_RE = re.compile(r"\b(top|highest|best|most|largest|leading)\b", re.I)
_BOTTOM_RE = re.compile(r"\b(bottom|lowest|worst|least|smallest|weakest)\b", re.I)
_TREND_RE = re.compile(r"\b(trend|over time|by month|monthly|growth|decline|change|per (day|week|month|quarter|year))\b", re.I)
_DISTRIB_RE = re.compile(r"\b(distribution|spread|histogram|range of)\b", re.I)
_COUNT_RE = re.compile(r"\b(how many|number of|count)\b", re.I)
_AVG_RE = re.compile(r"\b(average|mean|typical)\b", re.I)
_TOPN_RE = re.compile(r"\btop\s+(\d{1,3})\b", re.I)


def _pick_measure(profile: DatasetProfile, question: str) -> str | None:
    q = question.lower()
    # Prefer a measure whose name the question mentions.
    for col in profile.columns:
        if col.name in profile.measure_columns and _mentions(q, col.name):
            return col.name
    return profile.primary_measure_column or (
        profile.measure_columns[0] if profile.measure_columns else None
    )


def _pick_dimension(profile: DatasetProfile, question: str) -> str | None:
    q = question.lower()
    for col in profile.columns:
        if col.name in profile.dimension_columns and _mentions(q, col.name):
            return col.name
    # Categorical columns are dimensions even if not flagged.
    candidates = [
        c.name
        for c in profile.columns
        if c.inferred_type in (InferredType.CATEGORICAL, InferredType.BOOLEAN)
        and c.semantic_role != SemanticRole.IDENTIFIER
        and 1 < c.unique <= 60
    ]
    for name in candidates:
        if _mentions(q, name):
            return name
    return candidates[0] if candidates else None


def _mentions(question: str, column: str) -> bool:
    words = re.split(r"[^a-z0-9]+", column.lower())
    return any(w and w in question for w in words)


def keyword_plan(profile: DatasetProfile, question: str) -> LLMAskPlan:
    """A best-effort plan from keywords — used with no LLM, and as the seed."""
    q = question.lower()
    measure = _pick_measure(profile, question)
    dimension = _pick_dimension(profile, question)

    limit = 10
    if match := _TOPN_RE.search(q):
        limit = max(1, min(int(match.group(1)), 50))

    aggregation = Aggregation.SUM
    if _COUNT_RE.search(q) or measure is None:
        aggregation = Aggregation.COUNT
    elif _AVG_RE.search(q):
        aggregation = Aggregation.AVG
    else:
        col = profile.column(measure) if measure else None
        if col and col.semantic_role in (SemanticRole.PERCENTAGE, SemanticRole.RATIO):
            aggregation = Aggregation.AVG

    if _TREND_RE.search(q) and profile.primary_date_column:
        intent = "trend"
    elif _DISTRIB_RE.search(q) and measure:
        intent = "distribution"
    elif _BOTTOM_RE.search(q) and dimension:
        intent = "rank"
    elif _TOP_RE.search(q) and dimension:
        intent = "rank"
    elif dimension and measure:
        intent = "rank"
    else:
        intent = "aggregate"

    sort = "value_asc" if _BOTTOM_RE.search(q) else "value_desc"

    return LLMAskPlan(
        intent=intent,
        measure_column=measure,
        aggregation=aggregation,
        dimension_column=dimension,
        date_column=profile.primary_date_column,
        limit=limit,
        sort=sort,
    )


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _validate_plan(plan: LLMAskPlan, profile: DatasetProfile) -> LLMAskPlan:
    """Drop any column the dataset does not actually have."""
    names = {c.name for c in profile.columns}

    if plan.measure_column not in names:
        plan.measure_column = None
    if plan.dimension_column not in names:
        plan.dimension_column = None
    if plan.date_column not in names:
        plan.date_column = None
    if plan.filter_column not in names:
        plan.filter_column = None
        plan.filter_value = None

    # A measure must be numeric; fall back to counting rows otherwise.
    if plan.measure_column:
        col = profile.column(plan.measure_column)
        if col and col.inferred_type != InferredType.NUMERIC:
            plan.measure_column = None
            plan.aggregation = Aggregation.COUNT

    if plan.intent == "trend" and not plan.date_column:
        plan.date_column = profile.primary_date_column
        if not plan.date_column:
            plan.intent = "rank" if plan.dimension_column else "aggregate"

    if plan.intent == "rank" and not plan.dimension_column:
        plan.intent = "aggregate"

    plan.limit = max(1, min(int(plan.limit or 10), 50))
    return plan


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------


def _extra_filter(plan: LLMAskPlan, profile: DatasetProfile) -> list[FilterValue]:
    if plan.filter_column and plan.filter_value:
        return [
            FilterValue(
                column=plan.filter_column,
                operator="in",
                value=[plan.filter_value],
            )
        ]
    return []


def _grain(profile: DatasetProfile, plan: LLMAskPlan) -> TimeGrain:
    if plan.time_grain:
        return plan.time_grain
    if plan.date_column:
        col = profile.column(plan.date_column)
        if col and col.datetime and col.datetime.suggested_grain:
            try:
                return TimeGrain(col.datetime.suggested_grain)
            except ValueError:
                pass
    return TimeGrain.MONTH


def _measure_label(plan: LLMAskPlan) -> str:
    if not plan.measure_column:
        return "record count"
    return humanize(plan.measure_column)


def _fmt(profile: DatasetProfile, plan: LLMAskPlan, value: float | None) -> str:
    from ..utils.formatting import compact_number

    if value is None:
        return "—"
    if plan.measure_column:
        col = profile.column(plan.measure_column)
        if col and col.semantic_role == SemanticRole.CURRENCY:
            return f"${compact_number(value)}"
        if col and col.semantic_role == SemanticRole.PERCENTAGE:
            return f"{value:,.1f}%"
    return compact_number(value)


def execute_plan(
    plan: LLMAskPlan,
    profile: DatasetProfile,
    query: DatasetQuery,
    *,
    settings: Settings,
    base_filters: list[FilterValue],
) -> ExecutedPlan:
    """Run the validated plan and assemble the grounded result."""
    filters = list(base_filters) + _extra_filter(plan, profile)
    available = set(query.columns)
    measure_label = _measure_label(plan)
    agg_word = plan.aggregation.value

    # -- RANK: top/bottom by a dimension ----------------------------------
    if plan.intent == "rank" and plan.dimension_column:
        frame = query.aggregate_by_dimension(
            plan.dimension_column,
            plan.measure_column,
            plan.aggregation,
            filters=filters,
            limit=plan.limit,
            sort=plan.sort,
        ).dropna(subset=["value"])
        if frame.empty:
            return _empty(plan, "No rows matched that question.")

        leader = frame.iloc[0]
        direction = "lowest" if plan.sort == "value_asc" else "highest"
        headline = (
            f"{leader['label']} has the {direction} {measure_label.lower()} "
            f"at {_fmt(profile, plan, float(leader['value']))}."
        )
        evidence = [
            AskEvidence(
                label=f"{humanize(plan.dimension_column)}: {row['label']}",
                value=_fmt(profile, plan, float(row["value"])),
            )
            for _, row in frame.head(5).iterrows()
        ]
        chart = _chart_for(
            {
                "type": "bar" if len(frame) > 5 else "bar",
                "x": plan.dimension_column,
                "y": plan.measure_column,
                "aggregation": agg_word,
                "title": f"{humanize(measure_label)} by {humanize(plan.dimension_column)}",
                "sort": plan.sort,
                "limit": plan.limit,
            },
            profile,
            settings=settings,
            available=available,
        )
        facts = [
            f"{row['label']}: {_fmt(profile, plan, float(row['value']))}"
            for _, row in frame.head(plan.limit).iterrows()
        ]
        return ExecutedPlan(
            intent="rank",
            headline=headline,
            evidence=evidence,
            table=frame.rename(columns={"label": humanize(plan.dimension_column), "value": measure_label}),
            chart=chart,
            summary_for_llm={
                "question_type": "ranking",
                "dimension": plan.dimension_column,
                "measure": measure_label,
                "aggregation": agg_word,
                "ranked": facts[:10],
            },
            interpretation=(
                f"Ranked {agg_word} of {measure_label} by "
                f"{humanize(plan.dimension_column)}."
            ),
            facts=facts,
        )

    # -- TREND: over time --------------------------------------------------
    if plan.intent == "trend" and plan.date_column:
        grain = _grain(profile, plan)
        frame = query.time_series(
            plan.date_column,
            plan.measure_column,
            plan.aggregation if plan.measure_column else Aggregation.COUNT,
            grain,
            filters=filters,
        ).dropna(subset=["period"])
        if len(frame) < 2:
            return _empty(plan, "Not enough dated rows to describe a trend.")

        values = pd.to_numeric(frame["value"], errors="coerce")
        first, last = float(values.iloc[0]), float(values.iloc[-1])
        change = ((last - first) / abs(first) * 100) if first else None
        best_idx = int(values.to_numpy().argmax())
        best_period = pd.Timestamp(frame["period"].iloc[best_idx])
        headline = (
            f"{humanize(measure_label)} went from {_fmt(profile, plan, first)} to "
            f"{_fmt(profile, plan, last)}"
            + (f" ({change:+.1f}%)" if change is not None else "")
            + f" over the period, peaking around {best_period.strftime('%b %Y')}."
        )
        evidence = [
            AskEvidence(label="Start", value=_fmt(profile, plan, first)),
            AskEvidence(label="End", value=_fmt(profile, plan, last)),
            AskEvidence(
                label="Change",
                value=f"{change:+.1f}%" if change is not None else "—",
            ),
        ]
        chart = _chart_for(
            {
                "type": "line",
                "x": plan.date_column,
                "y": plan.measure_column,
                "aggregation": agg_word,
                "time_grain": grain.value,
                "title": f"{humanize(measure_label)} Over Time",
            },
            profile,
            settings=settings,
            available=available,
        )
        return ExecutedPlan(
            intent="trend",
            headline=headline,
            evidence=evidence,
            table=frame.assign(
                period=frame["period"].astype(str)
            ).rename(columns={"period": "Period", "value": measure_label})[
                ["Period", measure_label]
            ],
            chart=chart,
            summary_for_llm={
                "question_type": "trend",
                "measure": measure_label,
                "grain": grain.value,
                "first_value": round(first, 2),
                "last_value": round(last, 2),
                "change_pct": round(change, 2) if change is not None else None,
                "peak_period": best_period.strftime("%Y-%m"),
            },
            interpretation=f"{humanize(measure_label)} aggregated by {grain.value}.",
            facts=[headline],
        )

    # -- DISTRIBUTION ------------------------------------------------------
    if plan.intent == "distribution" and plan.measure_column:
        col = profile.column(plan.measure_column)
        stats = col.numeric if col else None
        if not stats:
            return _empty(plan, "That column has no numeric distribution.")
        headline = (
            f"{humanize(plan.measure_column)} ranges from "
            f"{_fmt(profile, plan, stats.min)} to {_fmt(profile, plan, stats.max)}, "
            f"with a median of {_fmt(profile, plan, stats.median)}."
        )
        evidence = [
            AskEvidence(label="Minimum", value=_fmt(profile, plan, stats.min)),
            AskEvidence(label="Median", value=_fmt(profile, plan, stats.median)),
            AskEvidence(label="Mean", value=_fmt(profile, plan, stats.mean)),
            AskEvidence(label="Maximum", value=_fmt(profile, plan, stats.max)),
        ]
        chart = _chart_for(
            {"type": "histogram", "x": plan.measure_column, "aggregation": "count",
             "title": f"Distribution of {humanize(plan.measure_column)}"},
            profile, settings=settings, available=available,
        )
        return ExecutedPlan(
            intent="distribution",
            headline=headline,
            evidence=evidence,
            table=pd.DataFrame(
                [
                    {"Statistic": "Minimum", "Value": stats.min},
                    {"Statistic": "25th percentile", "Value": stats.p25},
                    {"Statistic": "Median", "Value": stats.median},
                    {"Statistic": "Mean", "Value": stats.mean},
                    {"Statistic": "75th percentile", "Value": stats.p75},
                    {"Statistic": "Maximum", "Value": stats.max},
                ]
            ),
            chart=chart,
            summary_for_llm={
                "question_type": "distribution",
                "column": plan.measure_column,
                "min": stats.min,
                "median": stats.median,
                "mean": stats.mean,
                "max": stats.max,
            },
            interpretation=f"Summary statistics for {humanize(plan.measure_column)}.",
            facts=[headline],
        )

    # -- AGGREGATE: a single number ---------------------------------------
    value = query.scalar(plan.measure_column, plan.aggregation, filters) if (
        plan.measure_column or plan.aggregation == Aggregation.COUNT
    ) else None
    if value is None and plan.aggregation == Aggregation.COUNT:
        value = float(query.row_count(filters))
    if value is None:
        return _empty(plan, "That value could not be computed from the data.")

    headline = (
        f"The {agg_word} of {measure_label} is {_fmt(profile, plan, value)}"
        + (
            f" for {plan.filter_value}."
            if plan.filter_value
            else " across the dataset."
        )
    )
    return ExecutedPlan(
        intent="aggregate",
        headline=headline,
        evidence=[
            AskEvidence(label=f"{agg_word.title()} {measure_label}", value=_fmt(profile, plan, value))
        ],
        table=pd.DataFrame([{measure_label: value}]),
        chart=None,
        summary_for_llm={
            "question_type": "aggregate",
            "measure": measure_label,
            "aggregation": agg_word,
            "value": round(value, 2),
            "filter": plan.filter_value,
        },
        interpretation=f"{agg_word.title()} of {measure_label}.",
        facts=[headline],
    )


def _chart_for(
    payload: dict[str, Any],
    profile: DatasetProfile,
    *,
    settings: Settings,
    available: set[str],
) -> ChartSpecification | None:
    try:
        return chart_builder.build_and_validate(
            payload, profile, settings=settings, available=available
        )
    except chart_builder.ChartBuildError:
        return None


def _empty(plan: LLMAskPlan, reason: str) -> ExecutedPlan:
    return ExecutedPlan(
        intent=plan.intent,
        headline=None,
        evidence=[],
        table=pd.DataFrame(),
        chart=None,
        summary_for_llm={"result": "no data", "reason": reason},
        interpretation=reason,
        warning=reason,
        facts=[reason],
    )


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


async def answer_question(
    question: str,
    profile: DatasetProfile,
    query: DatasetQuery,
    *,
    ai: AIService,
    settings: Settings,
    base_filters: list[FilterValue],
) -> AskResponse:
    """The full ask pipeline: plan → validate → compute → explain."""
    # -- plan ----------------------------------------------------------
    plan = keyword_plan(profile, question)
    if ai.is_enabled:
        llm_plan = await ai.structured(
            system=PLAN_SYSTEM,
            prompt=PLAN_TEMPLATE.format(
                name=profile.name,
                rows=profile.n_rows,
                fields=_fields_for_prompt(profile),
                date_col=profile.primary_date_column or "none",
                measure_col=profile.primary_measure_column or "none",
                question=question,
            ),
            schema=LLMAskPlan,
        )
        if llm_plan is not None:
            plan = llm_plan

    plan = _validate_plan(plan, profile)

    # -- compute (numbers are born here) -------------------------------
    try:
        executed = execute_plan(
            plan, profile, query, settings=settings, base_filters=base_filters
        )
    except QueryError as exc:
        log.warning("Ask execution failed: %s", exc)
        return AskResponse(
            question=question,
            answer="I couldn't compute an answer for that question against this dataset.",
            interpretation="",
            warning=str(exc),
        )

    # -- explain -------------------------------------------------------
    answer = executed.headline or executed.interpretation
    ai_used = False
    if ai.is_enabled and executed.headline:
        explanation = await ai.structured(
            system=EXPLAIN_SYSTEM,
            prompt=EXPLAIN_TEMPLATE.format(
                question=question,
                result=_result_for_prompt(executed),
            ),
            schema=LLMAskExplanation,
            temperature=0.2,
        )
        if explanation and explanation.answer.strip():
            answer = explanation.answer.strip()
            ai_used = True

    # -- assemble ------------------------------------------------------
    chart_payload: AskChart | None = None
    if executed.chart is not None:
        try:
            data = execute_chart(
                executed.chart, query, filters=base_filters, settings=settings
            )
            if data.row_count:
                chart_payload = AskChart(
                    chart=executed.chart.model_dump(mode="json"), data=data
                )
        except QueryError:
            chart_payload = None

    table_records = records(executed.table.head(50)) if not executed.table.empty else []
    table_columns = [str(c) for c in executed.table.columns] if not executed.table.empty else []

    return AskResponse(
        question=question,
        answer=answer,
        interpretation=executed.interpretation,
        evidence=executed.evidence,
        table=table_records,
        table_columns=table_columns,
        chart=chart_payload,
        ai_used=ai_used,
        warning=executed.warning,
    )


def _fields_for_prompt(profile: DatasetProfile) -> str:
    lines = []
    for col in profile.columns:
        role = col.semantic_role.value
        lines.append(f"- {col.name} ({col.inferred_type.value}, {role})")
    return "\n".join(lines)


def _result_for_prompt(executed: ExecutedPlan) -> str:
    import json

    payload = dict(executed.summary_for_llm)
    payload["headline_fact"] = executed.headline
    return json.dumps(payload, default=str, indent=2)[:2500]
