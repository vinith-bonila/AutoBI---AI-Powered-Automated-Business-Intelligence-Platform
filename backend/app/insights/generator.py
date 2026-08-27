"""Insight generation: deterministic baseline plus optional LLM narration.

The LLM's contribution is *language*, not facts. Its insights are accepted
only when the evidence labels they cite exist in the computed evidence index;
an insight resting on a metric we never calculated is discarded, because that
is exactly what a hallucination looks like.
"""

from __future__ import annotations

from ..ai.client import AIService
from ..ai.prompts import INSIGHT_SYSTEM, build_insight_prompt
from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import (
    KPI,
    Insight,
    InsightEvidence,
    LLMInsightResponse,
)
from ..schemas.enums import GenerationSource, InsightCategory, InsightSeverity
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport
from ..utils.formatting import format_pct_change, humanize
from ..utils.logging import get_logger
from .deterministic import generate_insights as generate_deterministic

log = get_logger(__name__)

MAX_INSIGHTS = 6
MIN_BODY_LENGTH = 40


def build_evidence_index(
    kpis: list[KPI], analysis: AnalysisResult, quality: DataQualityReport
) -> dict[str, InsightEvidence]:
    """Every metric the model is allowed to cite, keyed by a normalised label."""
    index: dict[str, InsightEvidence] = {}

    def add(metric: str, value: str, detail: str | None = None) -> None:
        index[_normalize(metric)] = InsightEvidence(
            metric=metric, value=value, detail=detail
        )

    for kpi in kpis:
        detail = kpi.calculation
        if kpi.comparison and kpi.comparison.change_pct is not None:
            detail += (
                f" — {format_pct_change(kpi.comparison.change_pct)} "
                f"{kpi.comparison.period_label}"
            )
        add(kpi.name, kpi.formatted_value, detail)

    for trend in analysis.trends:
        label = humanize(trend.measure)
        add(
            f"{label} change over period",
            format_pct_change(trend.change_pct),
            f"{trend.points[0].period} to {trend.points[-1].period}"
            if trend.points
            else None,
        )
        if trend.best_period:
            add(
                f"Best {trend.grain} for {label}",
                trend.best_period.period,
                f"{trend.best_period.value:,.0f}",
            )
        if trend.worst_period:
            add(
                f"Worst {trend.grain} for {label}",
                trend.worst_period.period,
                f"{trend.worst_period.value:,.0f}",
            )

    for segment in analysis.segments:
        dimension = humanize(segment.dimension)
        if segment.top:
            leader = segment.top[0]
            add(
                f"Top {dimension}",
                leader.label,
                f"{leader.value:,.0f} ({leader.share_pct:.1f}% of total)",
            )
        if segment.bottom:
            laggard = segment.bottom[-1]
            add(
                f"Lowest {dimension}",
                laggard.label,
                f"{laggard.value:,.0f} ({laggard.share_pct:.1f}%)",
            )
        if segment.concentration_pct is not None:
            add(
                f"Top 3 {dimension} share",
                f"{segment.concentration_pct:.1f}%",
                f"Across {segment.n_categories} categories.",
            )

    for pair in analysis.correlations:
        add(
            f"Correlation: {humanize(pair.x)} vs {humanize(pair.y)}",
            f"r = {pair.coefficient:.2f}",
            f"{pair.strength.title()} {pair.direction}, n = {pair.n:,}.",
        )

    for anomaly in analysis.anomalies:
        add(
            f"{humanize(anomaly.measure)} in {anomaly.period}",
            f"{anomaly.value:,.0f}",
            f"Expected around {anomaly.expected:,.0f} "
            f"({anomaly.deviation_pct:+.1f}%).",
        )

    for outlier in analysis.outliers:
        add(
            f"{humanize(outlier.column)} outliers",
            f"{outlier.count:,} rows",
            f"{outlier.pct:.1f}% outside 1.5x IQR.",
        )

    for distribution in analysis.distributions:
        if distribution.skew is not None:
            add(
                f"{humanize(distribution.column)} skew",
                f"{distribution.skew:.2f}",
                f"Distribution is {distribution.shape}.",
            )

    add(
        "Data quality score",
        f"{quality.quality_score:.0f}/100",
        f"{quality.rows_after:,} rows after cleaning.",
    )
    if quality.duplicates_removed:
        add(
            "Duplicate rows removed",
            f"{quality.duplicates_removed:,}",
            "Removed before any figure was calculated.",
        )
    for missing in quality.missing_summary[:5]:
        add(
            f"{missing.column} missing values",
            f"{missing.missing_pct:.1f}%",
            missing.strategy,
        )

    return index


def _normalize(label: str) -> str:
    return " ".join(label.lower().replace("`", "").split())


def _resolve_evidence(
    refs: list[str], index: dict[str, InsightEvidence]
) -> list[InsightEvidence]:
    """Map the model's citations onto real computed metrics."""
    resolved: list[InsightEvidence] = []
    seen: set[str] = set()
    for ref in refs:
        key = _normalize(ref)
        evidence = index.get(key)
        if evidence is None:
            # Tolerate near-misses ("Total Revenue change" vs the exact label)
            # by looking for a unique containment match.
            candidates = [
                v for k, v in index.items() if key and (key in k or k in key)
            ]
            evidence = candidates[0] if len(candidates) == 1 else None
        if evidence is not None and evidence.metric not in seen:
            seen.add(evidence.metric)
            resolved.append(evidence)
    return resolved


async def generate(
    profile: DatasetProfile,
    analysis: AnalysisResult,
    kpis: list[KPI],
    quality: DataQualityReport,
    *,
    ai: AIService,
    title: str,
    domain: str,
) -> tuple[list[Insight], list[str]]:
    """Produce the final insight list plus any notes about AI handling."""
    deterministic = generate_deterministic(profile, analysis, kpis, quality)
    notes: list[str] = []

    if not ai.is_enabled:
        return deterministic[:MAX_INSIGHTS], notes

    index = build_evidence_index(kpis, analysis, quality)
    prompt = build_insight_prompt(profile, title, domain, kpis, analysis, quality)

    response = await ai.structured(
        system=INSIGHT_SYSTEM,
        prompt=prompt,
        schema=LLMInsightResponse,
        temperature=0.3,
    )

    if response is None:
        notes.append(
            "AI insight generation did not return valid output; "
            "showing rule-based insights instead."
        )
        return deterministic[:MAX_INSIGHTS], notes

    accepted: list[Insight] = []
    rejected = 0
    for position, proposal in enumerate(response.insights):
        body = (proposal.body or "").strip()
        title_text = (proposal.title or "").strip()
        if len(body) < MIN_BODY_LENGTH or not title_text:
            rejected += 1
            continue

        evidence = _resolve_evidence(proposal.evidence_refs, index)
        if not evidence:
            # An insight with no traceable metric is exactly the failure mode
            # this design exists to prevent.
            rejected += 1
            log.debug("Rejected ungrounded AI insight: %s", title_text[:80])
            continue

        accepted.append(
            Insight(
                id=f"ai_{position}_{_slug(title_text)}",
                title=title_text,
                body=body,
                category=proposal.category or InsightCategory.SUMMARY,
                severity=proposal.severity or InsightSeverity.NEUTRAL,
                evidence=evidence,
                confidence=0.8,
                source=GenerationSource.AI,
            )
        )

    if rejected:
        notes.append(
            f"{rejected} AI insight(s) were discarded because they cited metrics "
            "that were never computed."
        )

    if not accepted:
        notes.append("No AI insight passed grounding checks; using rule-based insights.")
        return deterministic[:MAX_INSIGHTS], notes

    # Always retain the quality caveat: the model tends to skip it, and it is
    # the insight most likely to change how the rest should be read.
    quality_insight = next(
        (i for i in deterministic if i.category == InsightCategory.QUALITY), None
    )
    combined = accepted[:MAX_INSIGHTS]
    if quality_insight and not any(
        i.category == InsightCategory.QUALITY for i in combined
    ):
        combined = combined[: MAX_INSIGHTS - 1] + [quality_insight]

    log.info(
        "Insights: %d from AI, %d rejected, %d deterministic available",
        len(accepted), rejected, len(deterministic),
    )
    return combined, notes


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())[:40].strip("_")
