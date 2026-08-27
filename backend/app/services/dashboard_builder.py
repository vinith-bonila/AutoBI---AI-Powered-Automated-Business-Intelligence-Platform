"""Assembly of the final `DashboardSpecification`.

This is where the two halves of the system meet. The deterministic engine has
already decided what *can* be shown and computed every number; the LLM is then
given a chance to improve naming, ranking and framing. Anything it proposes is
re-validated against the same rules, so the worst case of an AI failure is a
dashboard that looks exactly like the deterministic one.
"""

from __future__ import annotations

import pandas as pd

from ..ai.client import AIService
from ..ai.prompts import SEMANTIC_SYSTEM, build_semantic_prompt
from ..analysis.query import DatasetQuery
from ..charts.recommender import apply_llm_chart_proposals, recommend_charts
from ..config import Settings
from ..insights import generator as insight_generator
from ..kpi.engine import apply_llm_proposals, calculate_kpis, discover_kpis
from ..schemas.analysis import AnalysisResult
from ..schemas.dashboard import (
    DashboardSpecification,
    FilterSpecification,
    LLMSemanticResponse,
)
from ..schemas.enums import (
    FilterKind,
    FilterOperator,
    GenerationSource,
    InferredType,
    SemanticRole,
)
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport
from ..utils.formatting import humanize
from ..utils.logging import get_logger

log = get_logger(__name__)

MAX_FILTERS = 5
MAX_FILTER_OPTIONS = 60


def build_filters(
    profile: DatasetProfile,
    query: DatasetQuery,
    *,
    settings: Settings,
    available: set[str],
) -> list[FilterSpecification]:
    """Generate filters for the dimensions a user would actually slice by."""
    filters: list[FilterSpecification] = []

    # A date range filter first — it is the control people reach for most.
    date_column = profile.primary_date_column
    if date_column and date_column in available:
        lo, hi = query.column_range(date_column)
        if lo is not None and hi is not None:
            filters.append(
                FilterSpecification(
                    id=f"filter_{date_column}",
                    column=date_column,
                    label=humanize(date_column),
                    kind=FilterKind.DATE_RANGE,
                    operator=FilterOperator.BETWEEN,
                    min=pd.Timestamp(lo).isoformat(),
                    max=pd.Timestamp(hi).isoformat(),
                )
            )

    # Then the most useful categorical dimensions.
    candidates = [
        c
        for c in profile.columns
        if c.name in available
        and c.inferred_type in (InferredType.CATEGORICAL, InferredType.BOOLEAN)
        and c.semantic_role != SemanticRole.IDENTIFIER
        and not c.is_constant
        and 1 < c.unique <= MAX_FILTER_OPTIONS
    ]
    # Prefer fewer, cleaner categories.
    candidates.sort(
        key=lambda c: (
            0 if c.semantic_role in (SemanticRole.GEO, SemanticRole.DIMENSION) else 1,
            c.unique,
        )
    )

    for column in candidates[: MAX_FILTERS - len(filters)]:
        try:
            options = query.distinct_values(column.name, limit=MAX_FILTER_OPTIONS)
        except Exception as exc:  # QueryError
            log.debug("Filter skipped for %s: %s", column.name, exc)
            continue
        if len(options) < 2:
            continue
        filters.append(
            FilterSpecification(
                id=f"filter_{column.name}",
                column=column.name,
                label=humanize(column.name),
                kind=FilterKind.MULTI_SELECT,
                operator=FilterOperator.IN,
                options=sorted(options, key=str),
            )
        )

    return filters


async def build_dashboard(
    *,
    frame: pd.DataFrame,
    profile: DatasetProfile,
    analysis: AnalysisResult,
    quality: DataQualityReport,
    query: DatasetQuery,
    ai: AIService,
    settings: Settings,
) -> DashboardSpecification:
    """Produce the complete, validated dashboard specification."""
    available = {str(c) for c in frame.columns}
    notes: list[str] = []

    # -- 1. deterministic baseline ----------------------------------------
    kpi_definitions = discover_kpis(profile, settings=settings)
    charts = recommend_charts(
        profile, analysis, settings=settings, available_columns=available
    )

    domain = profile.domain_guess or "general"
    title = f"{humanize(profile.name.replace('.csv', ''))} Dashboard"
    description = ""
    source = GenerationSource.DETERMINISTIC

    # -- 2. LLM semantic pass ---------------------------------------------
    if ai.is_enabled:
        semantic = await ai.structured(
            system=SEMANTIC_SYSTEM,
            prompt=build_semantic_prompt(
                profile,
                existing_kpis=[d.name for d in kpi_definitions[:8]],
                existing_charts=[f"{c.type.value}: {c.title}" for c in charts],
            ),
            schema=LLMSemanticResponse,
        )
        if semantic is None:
            notes.append(
                "Semantic analysis did not return valid output; the dashboard was "
                "built from deterministic rules only."
            )
        else:
            source = GenerationSource.HYBRID
            if semantic.dataset_title.strip():
                title = semantic.dataset_title.strip()
            if semantic.dataset_description.strip():
                description = semantic.dataset_description.strip()
            if semantic.domain.strip():
                domain = semantic.domain.strip().lower()

            kpi_definitions = apply_llm_proposals(
                kpi_definitions, semantic.kpis, profile
            )
            charts, chart_notes = apply_llm_chart_proposals(
                charts,
                semantic.charts,
                profile,
                settings=settings,
                available_columns=available,
            )
            notes.extend(chart_notes)
    else:
        notes.append(
            "No AI provider is configured — KPIs, charts and insights were "
            "generated from deterministic rules."
        )

    # -- 3. compute KPI values (always in Python) --------------------------
    kpis = calculate_kpis(kpi_definitions, query, profile)

    # -- 4. filters --------------------------------------------------------
    filters = build_filters(
        profile, query, settings=settings, available=available
    )

    # -- 5. insights -------------------------------------------------------
    insights, insight_notes = await insight_generator.generate(
        profile, analysis, kpis, quality, ai=ai, title=title, domain=domain
    )
    notes.extend(insight_notes)

    if not description:
        from ..insights.deterministic import summarize_dataset

        description = summarize_dataset(profile, kpis, analysis)

    specification = DashboardSpecification(
        dataset_id=profile.dataset_id,
        title=title,
        description=description,
        domain=domain,
        kpis=kpis,
        charts=charts,
        filters=filters,
        insights=insights,
        source=source,
        ai_provider=ai.provider_name,
        ai_notes=notes,
    )

    log.info(
        "Dashboard for %s: %d KPIs, %d charts, %d filters, %d insights (source=%s)",
        profile.name, len(kpis), len(charts), len(filters), len(insights),
        source.value,
    )
    return specification
