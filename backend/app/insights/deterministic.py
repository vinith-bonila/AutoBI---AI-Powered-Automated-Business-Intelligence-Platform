"""Rule-based insight generation.

These insights are produced without any LLM, directly from the analysis
output. They are the floor of the product: with no API key configured, the
dashboard still explains itself in plain English, and every sentence is
mechanically derived from a number the engine computed.
"""

from __future__ import annotations

from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import KPI, Insight, InsightEvidence
from ..schemas.enums import (
    GenerationSource,
    InsightCategory,
    InsightSeverity,
    ValueFormat,
)
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport
from ..utils.formatting import format_pct_change, format_value, humanize

CONCENTRATION_WARNING = 65.0
HIGH_MISSING_WARNING = 20.0
STRONG_SKEW = 1.5


def _direction_word(direction: str) -> str:
    return {"up": "increased", "down": "decreased", "flat": "held roughly steady"}.get(
        direction, "changed"
    )


def _severity_for_change(direction: str, favourable: bool = True) -> InsightSeverity:
    if direction == "flat":
        return InsightSeverity.NEUTRAL
    positive = (direction == "up") == favourable
    return InsightSeverity.POSITIVE if positive else InsightSeverity.WARNING


def _is_cost_measure(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in ("cost", "expense", "spend", "churn", "attrition", "defect")
    )


def generate_insights(
    profile: DatasetProfile,
    analysis: AnalysisResult,
    kpis: list[KPI],
    quality: DataQualityReport,
) -> list[Insight]:
    """Build the deterministic insight set for a dataset."""
    insights: list[Insight] = []

    # -- 1. headline trend -------------------------------------------------
    if analysis.trends:
        trend = analysis.trends[0]
        measure_label = humanize(trend.measure)
        favourable = not _is_cost_measure(trend.measure)
        evidence = [
            InsightEvidence(
                metric=f"{measure_label} change over period",
                value=format_pct_change(trend.change_pct),
                detail=(
                    f"From {trend.first_value:,.0f} in {trend.points[0].period} "
                    f"to {trend.last_value:,.0f} in {trend.points[-1].period}."
                ),
            )
        ]
        if trend.best_period:
            evidence.append(
                InsightEvidence(
                    metric=f"Best {trend.grain}",
                    value=trend.best_period.period,
                    detail=f"{trend.best_period.value:,.0f}",
                )
            )
        if trend.volatility_pct is not None:
            evidence.append(
                InsightEvidence(
                    metric="Period-to-period volatility",
                    value=f"{trend.volatility_pct:.1f}%",
                    detail="Standard deviation as a share of the mean.",
                )
            )

        body = (
            f"{measure_label} {_direction_word(trend.direction)} by "
            f"{abs(trend.change_pct or 0):.1f}% between {trend.points[0].period} and "
            f"{trend.points[-1].period}, measured {trend.grain} by {trend.grain}. "
            f"The strongest {trend.grain} was {trend.best_period.period if trend.best_period else 'n/a'}"
        )
        if trend.worst_period:
            body += f" and the weakest was {trend.worst_period.period}."
        else:
            body += "."
        if trend.r_squared is not None and trend.r_squared > 0.5:
            body += (
                f" The movement is consistent rather than erratic "
                f"(R² = {trend.r_squared:.2f} against a straight line)."
            )
        elif trend.volatility_pct and trend.volatility_pct > 40:
            body += (
                f" Period-to-period values swing widely (volatility "
                f"{trend.volatility_pct:.0f}%), so single periods should not be "
                "read as turning points."
            )
        if trend.partial_period_excluded:
            body += (
                f" The final period ({trend.partial_period_excluded}) was excluded "
                "because it is incomplete."
            )

        insights.append(
            Insight(
                id="headline_trend",
                title=f"{measure_label} {_direction_word(trend.direction)} {format_pct_change(trend.change_pct)}",
                body=body,
                category=InsightCategory.TREND,
                severity=_severity_for_change(trend.direction, favourable),
                evidence=evidence,
                confidence=0.95,
            )
        )

    # -- 2. divergence between two measures --------------------------------
    if len(analysis.trends) >= 2:
        first, second = analysis.trends[0], analysis.trends[1]
        if (
            first.change_pct is not None
            and second.change_pct is not None
            and abs(first.change_pct - second.change_pct) > 15
        ):
            faster, slower = (
                (first, second)
                if first.change_pct > second.change_pct
                else (second, first)
            )
            insights.append(
                Insight(
                    id="measure_divergence",
                    title=(
                        f"{humanize(faster.measure)} is growing faster than "
                        f"{humanize(slower.measure)}"
                    ),
                    body=(
                        f"Over the same period {humanize(faster.measure)} moved "
                        f"{format_pct_change(faster.change_pct)} while "
                        f"{humanize(slower.measure)} moved "
                        f"{format_pct_change(slower.change_pct)}, a gap of "
                        f"{abs(faster.change_pct - slower.change_pct):.1f} percentage "
                        "points. Where these two measures are economically linked, a "
                        "gap this size usually shows up in margin."
                    ),
                    category=InsightCategory.TREND,
                    severity=InsightSeverity.NEUTRAL,
                    evidence=[
                        InsightEvidence(
                            metric=f"{humanize(faster.measure)} change",
                            value=format_pct_change(faster.change_pct),
                        ),
                        InsightEvidence(
                            metric=f"{humanize(slower.measure)} change",
                            value=format_pct_change(slower.change_pct),
                        ),
                    ],
                    confidence=0.75,
                )
            )

    # -- 3. leading and lagging segments -----------------------------------
    for segment in analysis.segments[:2]:
        if not segment.top:
            continue
        leader = segment.top[0]
        dimension_label = humanize(segment.dimension)
        measure_label = humanize(segment.measure)
        evidence = [
            InsightEvidence(
                metric=f"Top {dimension_label}",
                value=leader.label,
                detail=f"{leader.value:,.0f} ({leader.share_pct:.1f}% of total)",
            ),
            InsightEvidence(
                metric=f"Top 3 {dimension_label} share",
                value=f"{segment.concentration_pct:.1f}%"
                if segment.concentration_pct is not None
                else "n/a",
                detail=f"Across {segment.n_categories} categories.",
            ),
        ]
        body = (
            f"{leader.label} leads on {measure_label.lower()} with "
            f"{leader.value:,.0f}, which is {leader.share_pct:.1f}% of the total "
            f"across {segment.n_categories} {dimension_label.lower()} values."
        )
        if segment.bottom:
            laggard = segment.bottom[-1]
            body += (
                f" At the other end, {laggard.label} contributes "
                f"{laggard.value:,.0f} ({laggard.share_pct:.1f}%)."
            )
        concentrated = (
            segment.concentration_pct is not None
            and segment.concentration_pct > CONCENTRATION_WARNING
            and segment.n_categories > 3
        )
        if concentrated:
            body += (
                f" The top three account for {segment.concentration_pct:.0f}% of the "
                "total, so results depend heavily on a small number of segments."
            )
        if segment.has_negative_values:
            body += (
                " Shares are calculated against total magnitude because this "
                "measure contains both positive and negative values."
            )

        insights.append(
            Insight(
                id=f"segment_{segment.dimension}",
                title=f"{leader.label} leads {dimension_label.lower()} performance",
                body=body,
                category=InsightCategory.SEGMENT,
                severity=(
                    InsightSeverity.WARNING if concentrated else InsightSeverity.NEUTRAL
                ),
                evidence=evidence,
                confidence=0.9,
            )
        )

    # -- 4. anomalies ------------------------------------------------------
    if analysis.anomalies:
        anomaly = analysis.anomalies[0]
        insights.append(
            Insight(
                id="anomaly",
                title=(
                    f"{humanize(anomaly.measure)} in {anomaly.period} is well outside "
                    "its normal range"
                ),
                body=(
                    f"{humanize(anomaly.measure)} reached {anomaly.value:,.0f} in "
                    f"{anomaly.period}, against a local expectation of "
                    f"{anomaly.expected:,.0f} — a deviation of "
                    f"{anomaly.deviation_pct:+.1f}% ({anomaly.z_score:+.1f} standard "
                    "deviations from the surrounding periods). This is worth checking "
                    "before it is read as a trend: one-off promotions, data loading "
                    "gaps and seasonal spikes all produce this shape."
                ),
                category=InsightCategory.ANOMALY,
                severity=(
                    InsightSeverity.WARNING
                    if anomaly.deviation_pct < 0
                    else InsightSeverity.NEUTRAL
                ),
                evidence=[
                    InsightEvidence(
                        metric=f"{humanize(anomaly.measure)} in {anomaly.period}",
                        value=f"{anomaly.value:,.0f}",
                        detail=f"Expected around {anomaly.expected:,.0f}.",
                    ),
                    InsightEvidence(
                        metric="Deviation",
                        value=f"{anomaly.deviation_pct:+.1f}%",
                        detail=f"z-score {anomaly.z_score:+.2f}",
                    ),
                ],
                confidence=0.8,
            )
        )

    # -- 5. correlations ---------------------------------------------------
    if analysis.correlations:
        pair = analysis.correlations[0]
        insights.append(
            Insight(
                id="correlation",
                title=(
                    f"{humanize(pair.x)} and {humanize(pair.y)} move "
                    f"{'together' if pair.direction == 'positive' else 'in opposite directions'}"
                ),
                body=(
                    f"Across {pair.n:,} rows, {humanize(pair.x)} and "
                    f"{humanize(pair.y)} show a {pair.strength} {pair.direction} "
                    f"correlation (r = {pair.coefficient:.2f}). That means the two "
                    "measures track each other closely, but it does not establish "
                    "that one causes the other — a shared driver such as order size "
                    "or seasonality can produce the same pattern."
                ),
                category=InsightCategory.CORRELATION,
                severity=InsightSeverity.NEUTRAL,
                evidence=[
                    InsightEvidence(
                        metric=f"Correlation: {humanize(pair.x)} vs {humanize(pair.y)}",
                        value=f"r = {pair.coefficient:.2f}",
                        detail=f"{pair.strength.title()} {pair.direction}, n = {pair.n:,}.",
                    )
                ],
                confidence=0.85,
            )
        )

    # -- 6. distribution shape --------------------------------------------
    skewed = next(
        (
            d
            for d in analysis.distributions
            if d.skew is not None and abs(d.skew) > STRONG_SKEW
        ),
        None,
    )
    if skewed:
        column_profile = profile.column(skewed.column)
        mean = column_profile.numeric.mean if column_profile and column_profile.numeric else None
        median = column_profile.numeric.median if column_profile and column_profile.numeric else None
        body = (
            f"{humanize(skewed.column)} is {skewed.shape} (skew "
            f"{skewed.skew:.2f}), so most values sit well below the largest ones."
        )
        if mean is not None and median is not None and median:
            body += (
                f" The mean ({mean:,.1f}) sits "
                f"{abs(mean - median) / abs(median) * 100:.0f}% away from the median "
                f"({median:,.1f}); the median is the safer summary for this column."
            )
        insights.append(
            Insight(
                id=f"distribution_{skewed.column}",
                title=f"{humanize(skewed.column)} is heavily {skewed.shape}",
                body=body,
                category=InsightCategory.DISTRIBUTION,
                severity=InsightSeverity.NEUTRAL,
                evidence=[
                    InsightEvidence(
                        metric=f"{humanize(skewed.column)} skew",
                        value=f"{skewed.skew:.2f}",
                        detail=f"Distribution shape: {skewed.shape}.",
                    )
                ],
                confidence=0.8,
            )
        )

    # -- 7. data quality ---------------------------------------------------
    quality_notes: list[str] = []
    quality_evidence: list[InsightEvidence] = [
        InsightEvidence(
            metric="Data quality score",
            value=f"{quality.quality_score:.0f}/100",
            detail=(
                f"Completeness {quality.completeness_score:.0f}, "
                f"uniqueness {quality.uniqueness_score:.0f}, "
                f"consistency {quality.consistency_score:.0f}."
            ),
        )
    ]
    if quality.duplicates_removed:
        quality_notes.append(
            f"{quality.duplicates_removed:,} exact duplicate rows were removed before "
            "any figure was calculated"
        )
        quality_evidence.append(
            InsightEvidence(
                metric="Duplicate rows removed",
                value=f"{quality.duplicates_removed:,}",
                detail=f"{quality.duplicates_removed / max(quality.rows_before, 1) * 100:.1f}% of the upload.",
            )
        )
    worst_missing = [
        m for m in quality.missing_summary if m.missing_pct >= HIGH_MISSING_WARNING
    ]
    if worst_missing:
        listed = ", ".join(f"{m.column} ({m.missing_pct:.1f}%)" for m in worst_missing[:3])
        quality_notes.append(f"several columns are substantially incomplete: {listed}")
        quality_evidence.append(
            InsightEvidence(
                metric="Most incomplete column",
                value=f"{worst_missing[0].column}",
                detail=f"{worst_missing[0].missing_pct:.1f}% missing.",
            )
        )

    if quality_notes:
        insights.append(
            Insight(
                id="data_quality",
                title="Data quality caveats worth knowing",
                body=(
                    "Before reading the numbers above, note that "
                    + "; and ".join(quality_notes)
                    + ". Missing numeric values are excluded from aggregations rather "
                    "than filled in, so totals reflect only the rows that carried a "
                    "value."
                ),
                category=InsightCategory.QUALITY,
                severity=(
                    InsightSeverity.WARNING
                    if quality.quality_score < 85
                    else InsightSeverity.NEUTRAL
                ),
                evidence=quality_evidence,
                confidence=1.0,
            )
        )

    # -- 8. a concrete suggestion -----------------------------------------
    recommendation = _build_recommendation(analysis, kpis)
    if recommendation:
        insights.append(recommendation)

    return insights


def _build_recommendation(
    analysis: AnalysisResult, kpis: list[KPI]
) -> Insight | None:
    """Derive one actionable suggestion from the strongest available signal."""
    # Concentration risk is the most commonly actionable pattern.
    for segment in analysis.segments:
        if (
            segment.concentration_pct
            and segment.concentration_pct > CONCENTRATION_WARNING
            and segment.n_categories >= 5
            and segment.top
        ):
            return Insight(
                id="recommendation",
                title=f"Reduce dependence on the top {humanize(segment.dimension).lower()} values",
                body=(
                    f"{segment.concentration_pct:.0f}% of "
                    f"{humanize(segment.measure).lower()} comes from just three of "
                    f"{segment.n_categories} {humanize(segment.dimension).lower()} "
                    f"values, led by {segment.top[0].label}. Concentration this high "
                    "makes results sensitive to a single segment underperforming. "
                    "Worth testing whether the long tail is under-invested or "
                    "genuinely low-potential before deciding where to push."
                ),
                category=InsightCategory.RECOMMENDATION,
                severity=InsightSeverity.WARNING,
                evidence=[
                    InsightEvidence(
                        metric=f"Top 3 {humanize(segment.dimension)} share",
                        value=f"{segment.concentration_pct:.1f}%",
                        detail=f"Of {segment.n_categories} categories.",
                    )
                ],
                confidence=0.7,
            )

    # A KPI moving unfavourably is the next most useful thing to flag.
    for kpi in kpis:
        if (
            kpi.comparison
            and kpi.comparison.is_favorable is False
            and kpi.comparison.change_pct is not None
            and abs(kpi.comparison.change_pct) >= 5
        ):
            return Insight(
                id="recommendation",
                title=f"{kpi.name} is moving the wrong way",
                body=(
                    f"{kpi.name} is {kpi.formatted_value}, "
                    f"{format_pct_change(kpi.comparison.change_pct)} "
                    f"{kpi.comparison.period_label}. {kpi.why_it_matters} "
                    "Worth isolating which segment drove the change before acting on "
                    "the headline figure."
                ),
                category=InsightCategory.RECOMMENDATION,
                severity=InsightSeverity.WARNING,
                evidence=[
                    InsightEvidence(
                        metric=kpi.name,
                        value=kpi.formatted_value,
                        detail=(
                            f"{format_pct_change(kpi.comparison.change_pct)} "
                            f"{kpi.comparison.period_label}."
                        ),
                    )
                ],
                confidence=0.75,
            )

    if analysis.outliers:
        outlier = analysis.outliers[0]
        return Insight(
            id="recommendation",
            title=f"Review the extreme values in {humanize(outlier.column)}",
            body=(
                f"{outlier.count:,} rows ({outlier.pct:.1f}%) fall outside the normal "
                f"range of {humanize(outlier.column)} (below {outlier.lower_bound:,.0f} "
                f"or above {outlier.upper_bound:,.0f}). Genuine extremes are worth "
                "understanding; data-entry errors are worth correcting. Either way "
                "they pull averages away from what a typical row looks like."
            ),
            category=InsightCategory.RECOMMENDATION,
            severity=InsightSeverity.NEUTRAL,
            evidence=[
                InsightEvidence(
                    metric=f"{humanize(outlier.column)} outliers",
                    value=f"{outlier.count:,} rows",
                    detail=f"{outlier.pct:.1f}% of the dataset, by the 1.5x IQR rule.",
                )
            ],
            confidence=0.7,
        )

    return None


def summarize_dataset(
    profile: DatasetProfile, kpis: list[KPI], analysis: AnalysisResult
) -> str:
    """A one-paragraph dashboard description used when no LLM is configured."""
    parts = [
        f"{profile.n_rows:,} rows across {profile.n_columns} columns"
    ]
    if profile.primary_date_column:
        col = profile.column(profile.primary_date_column)
        if col and col.datetime and col.datetime.min and col.datetime.max:
            parts.append(
                f"covering {col.datetime.min[:10]} to {col.datetime.max[:10]}"
            )
    if kpis:
        headline = kpis[0]
        parts.append(f"{headline.name.lower()} of {headline.formatted_value}")
    if analysis.segments:
        segment = analysis.segments[0]
        parts.append(
            f"broken down across {segment.n_categories} "
            f"{humanize(segment.dimension).lower()} values"
        )
    return "Analysis of " + ", ".join(parts) + "."
