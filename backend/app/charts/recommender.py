"""Chart recommendation.

Charts are proposed from the shape of the data using classic
visualisation-grammar rules:

    date + measure          -> line
    category + measure      -> bar / horizontal bar
    small category share    -> donut
    two measures            -> scatter
    one measure             -> histogram
    many measures           -> correlation heatmap
    detail rows             -> table

The LLM may reorder, retitle or suggest additional charts, but every chart —
its own or the model's — must pass `validator.validate_chart` before it can
reach the dashboard.
"""

from __future__ import annotations

from ..analysis.eda import rank_measures
from ..config import Settings
from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import ChartSpecification, LLMChartProposal
from ..schemas.enums import (
    Aggregation,
    ChartType,
    GenerationSource,
    InferredType,
    SemanticRole,
    TimeGrain,
)
from ..schemas.profile import DatasetProfile
from ..utils.formatting import humanize
from ..utils.logging import get_logger
from .validator import validate_chart, validate_charts

log = get_logger(__name__)

MAX_PRIMARY_CHARTS = 4
# Five slots so the correlation heatmap and the detail table both survive
# alongside the three analytical charts.
MAX_SECONDARY_CHARTS = 5


def _grain(profile: DatasetProfile, date_column: str) -> TimeGrain:
    col = profile.column(date_column)
    try:
        return TimeGrain(col.datetime.suggested_grain) if col and col.datetime else TimeGrain.MONTH
    except ValueError:
        return TimeGrain.MONTH


def _aggregation(profile: DatasetProfile, measure: str) -> Aggregation:
    from ..analysis.eda import _measure_aggregation

    return _measure_aggregation(profile, measure)


def _agg_word(aggregation: Aggregation) -> str:
    return {
        Aggregation.SUM: "Total",
        Aggregation.AVG: "Average",
        Aggregation.MEDIAN: "Median",
        Aggregation.MIN: "Minimum",
        Aggregation.MAX: "Maximum",
        Aggregation.COUNT: "Count of",
        Aggregation.COUNT_DISTINCT: "Distinct",
    }.get(aggregation, "Total")


def _usable_dimensions(
    profile: DatasetProfile, settings: Settings, *, available: set[str]
) -> list[str]:
    """Dimensions worth grouping by, best first."""
    scored: list[tuple[float, str]] = []
    for col in profile.columns:
        if col.name not in available:
            continue
        if col.inferred_type not in (InferredType.CATEGORICAL, InferredType.BOOLEAN):
            continue
        if col.semantic_role == SemanticRole.IDENTIFIER or col.is_constant:
            continue
        if col.unique < 2 or col.unique > settings.max_categorical_cardinality:
            continue
        # 4-12 categories is the sweet spot for a readable chart.
        if 3 <= col.unique <= 12:
            shape_score = 3.0
        elif col.unique <= 20:
            shape_score = 2.0
        else:
            shape_score = 1.0
        role_score = {
            SemanticRole.GEO: 1.5,
            SemanticRole.DIMENSION: 1.2,
            SemanticRole.DEMOGRAPHIC: 1.0,
            SemanticRole.FLAG: 0.6,
        }.get(col.semantic_role, 0.8)
        completeness = 1.0 - (col.missing_pct / 100.0)
        scored.append((shape_score * role_score * completeness, col.name))

    scored.sort(key=lambda item: -item[0])
    return [name for _, name in scored]


def recommend_charts(
    profile: DatasetProfile,
    analysis: AnalysisResult,
    *,
    settings: Settings,
    available_columns: set[str] | None = None,
) -> list[ChartSpecification]:
    """Build the deterministic chart set for a dataset."""
    available = available_columns or {c.name for c in profile.columns}
    charts: list[ChartSpecification] = []

    measures = rank_measures(
        profile, [m for m in profile.measure_columns if m in available]
    )
    primary_measure = profile.primary_measure_column
    date_column = profile.primary_date_column
    dimensions = _usable_dimensions(profile, settings, available=available)

    # -- 1. the headline trend --------------------------------------------
    if date_column and primary_measure:
        aggregation = _aggregation(profile, primary_measure)
        charts.append(
            ChartSpecification(
                id=f"trend_{primary_measure}",
                type=ChartType.LINE,
                title=f"{_agg_word(aggregation)} {humanize(primary_measure)} Over Time",
                description=(
                    f"{humanize(primary_measure)} aggregated by "
                    f"{_grain(profile, date_column).value}."
                ),
                x=date_column,
                y=primary_measure,
                aggregation=aggregation,
                time_grain=_grain(profile, date_column),
                section="primary",
                width="full",
                rationale="A date column and a measure make a time trend the "
                "single most informative view of this dataset.",
            )
        )
    elif date_column:
        charts.append(
            ChartSpecification(
                id="trend_volume",
                type=ChartType.LINE,
                title="Record Volume Over Time",
                description="How many rows fall in each period.",
                x=date_column,
                y=None,
                aggregation=Aggregation.COUNT,
                time_grain=_grain(profile, date_column),
                section="primary",
                width="full",
                rationale="No numeric measure was available, so volume over "
                "time is the meaningful trend.",
            )
        )

    # -- 2. ranked breakdown by the strongest dimension --------------------
    if dimensions:
        top_dimension = dimensions[0]
        dim_profile = profile.column(top_dimension)
        aggregation = (
            _aggregation(profile, primary_measure) if primary_measure else Aggregation.COUNT
        )
        many = dim_profile is not None and dim_profile.unique > 8
        charts.append(
            ChartSpecification(
                id=f"breakdown_{top_dimension}",
                type=ChartType.HORIZONTAL_BAR if many else ChartType.BAR,
                title=(
                    f"{_agg_word(aggregation)} "
                    f"{humanize(primary_measure) if primary_measure else 'Records'} "
                    f"by {humanize(top_dimension)}"
                ),
                description=f"Ranked contribution of each {humanize(top_dimension).lower()}.",
                x=top_dimension,
                y=primary_measure,
                aggregation=aggregation,
                sort="value_desc",
                limit=settings.max_chart_categories,
                section="primary",
                width="half" if not many else "full",
                rationale="A categorical dimension against a measure ranks "
                "performance and exposes concentration.",
            )
        )

    # -- 3. share of total -------------------------------------------------
    share_dimension = next(
        (
            name
            for name in dimensions
            if (p := profile.column(name)) and 2 <= p.unique <= 8
        ),
        None,
    )
    if share_dimension:
        aggregation = (
            _aggregation(profile, primary_measure) if primary_measure else Aggregation.COUNT
        )
        charts.append(
            ChartSpecification(
                id=f"share_{share_dimension}",
                type=ChartType.DONUT,
                title=f"Share of {humanize(primary_measure) if primary_measure else 'Records'} by {humanize(share_dimension)}",
                description="Contribution of each category to the total.",
                x=share_dimension,
                y=primary_measure,
                aggregation=aggregation,
                limit=8,
                section="primary",
                width="half",
                rationale="A small set of categories makes parts-of-a-whole "
                "readable.",
            )
        )

    # -- 4. trend split by dimension --------------------------------------
    if date_column and primary_measure and dimensions:
        split = next(
            (
                name
                for name in dimensions
                if (p := profile.column(name)) and 2 <= p.unique <= 6
            ),
            None,
        )
        if split:
            charts.append(
                ChartSpecification(
                    id=f"trend_{primary_measure}_by_{split}",
                    type=ChartType.LINE,
                    title=f"{humanize(primary_measure)} Over Time by {humanize(split)}",
                    description=f"Trend split across the top {humanize(split).lower()} values.",
                    x=date_column,
                    y=primary_measure,
                    series=split,
                    aggregation=_aggregation(profile, primary_measure),
                    time_grain=_grain(profile, date_column),
                    section="secondary",
                    width="full",
                    rationale="Splitting the trend shows which segment drives "
                    "the overall movement.",
                )
            )

    # -- 5. second dimension breakdown ------------------------------------
    if len(dimensions) > 1 and primary_measure:
        second = dimensions[1]
        aggregation = _aggregation(profile, primary_measure)
        charts.append(
            ChartSpecification(
                id=f"breakdown_{second}",
                type=ChartType.BAR,
                title=f"{_agg_word(aggregation)} {humanize(primary_measure)} by {humanize(second)}",
                description=f"Comparison across {humanize(second).lower()}.",
                x=second,
                y=primary_measure,
                aggregation=aggregation,
                sort="value_desc",
                limit=settings.max_chart_categories,
                section="secondary",
                width="half",
                rationale="A second dimension gives a cross-check on the "
                "primary breakdown.",
            )
        )

    # -- 6. relationship between the two strongest-correlated measures -----
    if analysis.correlations:
        best = analysis.correlations[0]
        if best.x in available and best.y in available:
            charts.append(
                ChartSpecification(
                    id=f"scatter_{best.x}_{best.y}",
                    type=ChartType.SCATTER,
                    title=f"{humanize(best.x)} vs {humanize(best.y)}",
                    description=(
                        f"{best.strength.title()} {best.direction} relationship "
                        f"(r = {best.coefficient:.2f})."
                    ),
                    x=best.x,
                    y=best.y,
                    aggregation=Aggregation.NONE,
                    limit=settings.max_chart_points,
                    section="secondary",
                    width="half",
                    rationale=(
                        f"These two measures correlate at r = {best.coefficient:.2f}, "
                        "which is worth showing directly."
                    ),
                )
            )

    # -- 7. distribution of the headline measure ---------------------------
    distribution_column = next(
        (d.column for d in analysis.distributions if d.column in available),
        primary_measure if primary_measure in available else None,
    )
    if distribution_column:
        charts.append(
            ChartSpecification(
                id=f"histogram_{distribution_column}",
                type=ChartType.HISTOGRAM,
                title=f"Distribution of {humanize(distribution_column)}",
                description="How values are spread, and where the mass sits.",
                x=distribution_column,
                aggregation=Aggregation.COUNT,
                bins=20,
                section="secondary",
                width="half",
                rationale="The spread of a measure reveals skew and outliers "
                "that an average hides.",
            )
        )

    # -- 8. correlation heatmap -------------------------------------------
    numeric_measures = [
        c.name
        for c in profile.columns
        if c.name in available
        and c.inferred_type == InferredType.NUMERIC
        and c.semantic_role != SemanticRole.IDENTIFIER
        and not c.is_constant
    ]
    if len(numeric_measures) >= 3:
        charts.append(
            ChartSpecification(
                id="correlation_heatmap",
                type=ChartType.HEATMAP,
                title="Correlation Between Measures",
                description="Pearson correlation across the numeric columns.",
                columns=numeric_measures[:8],
                aggregation=Aggregation.NONE,
                section="secondary",
                width="half",
                rationale="With several numeric columns, a correlation matrix "
                "summarises every pairwise relationship at once.",
            )
        )

    # -- 9. detail table ---------------------------------------------------
    table_columns = _table_columns(profile, available, limit=7)
    if table_columns:
        order_by = primary_measure if primary_measure in table_columns else None
        charts.append(
            ChartSpecification(
                id="detail_table",
                type=ChartType.TABLE,
                title=(
                    f"Top Records by {humanize(order_by)}" if order_by else "Sample Records"
                ),
                description="Row-level detail behind the aggregates above.",
                columns=table_columns,
                y=order_by,
                aggregation=Aggregation.NONE,
                limit=100,
                section="secondary",
                width="full",
                rationale="Aggregates need a way back to the underlying rows.",
            )
        )

    kept, notes = validate_charts(
        charts, profile, settings=settings, available_columns=available
    )
    for note in notes:
        log.debug("Chart validation: %s", note)

    return _balance_sections(kept)


def _table_columns(
    profile: DatasetProfile, available: set[str], *, limit: int = 7
) -> list[str]:
    """Pick readable columns for the detail table."""
    ordered: list[str] = []
    for role in (
        SemanticRole.IDENTIFIER,
        SemanticRole.TIME,
        SemanticRole.DIMENSION,
        SemanticRole.GEO,
        SemanticRole.CURRENCY,
        SemanticRole.QUANTITY,
        SemanticRole.MEASURE,
        SemanticRole.PERCENTAGE,
    ):
        for col in profile.columns:
            if (
                col.name in available
                and col.semantic_role == role
                and col.name not in ordered
                and col.inferred_type != InferredType.TEXT
            ):
                ordered.append(col.name)
            if len(ordered) >= limit:
                return ordered
    if not ordered:
        ordered = [c.name for c in profile.columns if c.name in available][:limit]
    return ordered[:limit]


def _balance_sections(charts: list[ChartSpecification]) -> list[ChartSpecification]:
    """Cap each section so the dashboard stays readable."""
    primary = [c for c in charts if c.section == "primary"][:MAX_PRIMARY_CHARTS]
    rest = [c for c in charts if c.section != "primary"]

    # The detail table is the only way back from aggregates to real rows, so
    # it keeps a reserved slot instead of being truncated away by whichever
    # charts happen to be generated first.
    table = next((c for c in rest if c.type == ChartType.TABLE), None)
    others = [c for c in rest if c is not table]

    secondary = others[: MAX_SECONDARY_CHARTS - (1 if table else 0)]
    if table:
        secondary.append(table)

    # A dashboard with an empty top section promotes its best secondary chart.
    if not primary and secondary:
        promoted = secondary.pop(0)
        promoted.section = "primary"
        primary = [promoted]

    return primary + secondary


# --------------------------------------------------------------------------
# LLM proposals
# --------------------------------------------------------------------------


def apply_llm_chart_proposals(
    charts: list[ChartSpecification],
    proposals: list[LLMChartProposal],
    profile: DatasetProfile,
    *,
    settings: Settings,
    available_columns: set[str] | None = None,
) -> tuple[list[ChartSpecification], list[str]]:
    """Merge model-proposed charts into the deterministic set.

    Proposals are converted into the same `ChartSpecification` type and run
    through the same validator, so a chart the model invents is held to
    exactly the standard as one the rules produced.
    """
    available = available_columns or {c.name for c in profile.columns}
    existing = {
        (c.type, c.x, c.y, c.series, tuple(c.columns)) for c in charts
    }
    notes: list[str] = []
    added: list[ChartSpecification] = []

    for proposal in proposals:
        signature = (
            proposal.type,
            proposal.x,
            proposal.y,
            proposal.series,
            tuple(proposal.columns),
        )
        if signature in existing:
            continue

        slug = "_".join(
            part for part in (
                proposal.type.value,
                proposal.x or "",
                proposal.y or "",
            ) if part
        )[:60] or f"ai_chart_{len(added)}"

        try:
            candidate = ChartSpecification(
                id=f"ai_{slug}",
                type=proposal.type,
                title=proposal.title or "Proposed Chart",
                description=None,
                x=proposal.x,
                y=proposal.y,
                series=proposal.series,
                aggregation=proposal.aggregation,
                columns=proposal.columns,
                time_grain=(
                    _grain(profile, proposal.x)
                    if proposal.x and proposal.x == profile.primary_date_column
                    else None
                ),
                limit=settings.max_chart_categories,
                section="secondary",
                width="half",
                rationale=proposal.rationale or "Proposed by semantic analysis.",
                source=GenerationSource.AI,
            )
        except ValueError as exc:
            notes.append(f"Rejected proposed chart `{proposal.title}`: {exc}")
            continue

        result = validate_chart(
            candidate, profile, settings=settings, available_columns=available
        )
        if not result.ok:
            notes.append(f"Rejected proposed chart `{proposal.title}`: {result.reason}")
            continue

        existing.add(signature)
        added.append(candidate)

    combined = _balance_sections(charts + added)
    if added:
        log.info("Accepted %d chart proposals from the model", len(added))
    return combined, notes
