"""KPI discovery and calculation.

Split of responsibility:
  * *Which* KPIs matter is a judgement call — rules here propose a set, and the
    LLM may add or re-rank (see `apply_llm_proposals`).
  * *What the numbers are* is never a judgement call. Every value below is
    computed by DuckDB over the cleaned dataset. A KPI whose value cannot be
    computed is dropped rather than displayed with a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis.query import DatasetQuery, QueryError
from ..config import Settings
from ..schemas.api import FilterValue
from ..schemas.dashboard import KPI, KPIComparison, LLMKPIProposal
from ..schemas.enums import (
    Aggregation,
    GenerationSource,
    SemanticRole,
    TimeGrain,
    ValueFormat,
)
from ..schemas.profile import DatasetProfile
from ..utils.formatting import format_value, humanize
from ..utils.logging import get_logger
from . import catalog

log = get_logger(__name__)

MAX_KPIS = 6


@dataclass
class KPIDefinition:
    """An executable KPI: how to compute it, independent of any filter set."""

    id: str
    name: str
    format: ValueFormat
    calculation: str
    why_it_matters: str
    source_columns: list[str]
    priority: int
    higher_is_better: bool = True
    source: GenerationSource = GenerationSource.DETERMINISTIC

    # Exactly one of these calculation shapes is used.
    measure: str | None = None
    aggregation: Aggregation = Aggregation.SUM
    numerator: str | None = None
    numerator_agg: Aggregation = Aggregation.SUM
    denominator: str | None = None
    denominator_agg: Aggregation = Aggregation.SUM
    denominator_is_row_count: bool = False
    flag_column: str | None = None
    multiply: float = 1.0
    unit: str | None = None

    def compute(
        self, query: DatasetQuery, filters: list[FilterValue]
    ) -> float | None:
        """Evaluate the KPI against the dataset under the given filters."""
        try:
            if self.flag_column is not None:
                total = query.row_count(filters)
                if not total:
                    return None
                hits = query.conditional_count(self.flag_column, True, filters)
                return hits / total * 100.0

            if self.numerator is not None:
                num = query.scalar(self.numerator, self.numerator_agg, filters)
                if num is None:
                    return None
                if self.denominator_is_row_count:
                    den: float | None = float(query.row_count(filters))
                else:
                    den = query.scalar(
                        self.denominator, self.denominator_agg, filters
                    )
                if not den:
                    return None
                return (num / den) * self.multiply

            if self.aggregation == Aggregation.COUNT and self.measure is None:
                return float(query.row_count(filters))

            return query.scalar(self.measure, self.aggregation, filters)
        except QueryError as exc:
            log.debug("KPI %s could not be computed: %s", self.id, exc)
            return None


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def _aggregation_for(profile: DatasetProfile, column: str) -> Aggregation:
    from ..analysis.eda import _measure_aggregation

    return _measure_aggregation(profile, column)


def _format_for(profile: DatasetProfile, column: str) -> ValueFormat:
    col = profile.column(column)
    if col is None:
        return ValueFormat.NUMBER
    if col.semantic_role == SemanticRole.CURRENCY:
        return ValueFormat.CURRENCY
    if col.semantic_role == SemanticRole.PERCENTAGE:
        return ValueFormat.PERCENT
    if col.semantic_role == SemanticRole.QUANTITY:
        return ValueFormat.COUNT
    if col.semantic_role == SemanticRole.RATIO:
        return ValueFormat.DECIMAL
    return ValueFormat.NUMBER


def discover_kpis(
    profile: DatasetProfile, *, settings: Settings
) -> list[KPIDefinition]:
    """Propose KPI definitions from the dataset's shape and semantics."""
    definitions: list[KPIDefinition] = []
    domain = profile.domain_guess or "general"
    measures = catalog.measure_candidates(profile)

    # -- 1. record count ---------------------------------------------------
    label, why = catalog.record_label(domain)
    definitions.append(
        KPIDefinition(
            id="record_count",
            name=label,
            format=ValueFormat.COUNT,
            calculation="COUNT(*) over all rows matching the current filters",
            why_it_matters=why,
            source_columns=[],
            priority=70,
            aggregation=Aggregation.COUNT,
        )
    )

    # -- 2. headline totals / averages for each measure --------------------
    ranked = _rank_measures(profile, measures)
    for name in ranked[:4]:
        aggregation = _aggregation_for(profile, name)
        value_format = _format_for(profile, name)
        col = profile.column(name)
        is_primary = name == profile.primary_measure_column

        if aggregation == Aggregation.AVG:
            kpi_name = f"Average {humanize(name)}"
            calculation = f"AVG({name})"
            why = (
                f"The typical {humanize(name).lower()} across the filtered rows. "
                "Averages are used here because summing a per-unit value has no "
                "business meaning."
            )
            if value_format == ValueFormat.COUNT:
                value_format = ValueFormat.DECIMAL
        else:
            kpi_name = f"Total {humanize(name)}"
            calculation = f"SUM({name})"
            why = (
                f"The headline {humanize(name).lower()} figure for the current "
                "selection."
                if is_primary
                else f"Overall {humanize(name).lower()} contributed by the filtered rows."
            )

        definitions.append(
            KPIDefinition(
                id=f"{'avg' if aggregation == Aggregation.AVG else 'total'}_{name}",
                name=kpi_name,
                format=value_format,
                calculation=calculation,
                why_it_matters=why,
                source_columns=[name],
                priority=95 if is_primary else 65,
                measure=name,
                aggregation=aggregation,
                higher_is_better=not _is_cost_like(name),
            )
        )

    # -- 3. ratio rules ----------------------------------------------------
    for rule in catalog.RATIO_RULES:
        if rule.domains and domain not in rule.domains:
            continue
        numerator = catalog.find_column(profile, rule.numerator, candidates=measures)
        if numerator is None:
            continue

        if rule.denominator == ("__row_count__",):
            denominator_name, denominator_is_rows = None, True
        else:
            denominator = catalog.find_column(
                profile, rule.denominator, candidates=measures
            )
            if denominator is None or denominator.column == numerator.column:
                continue
            denominator_name, denominator_is_rows = denominator.column, False

        calculation = (
            f"SUM({numerator.column}) / COUNT(*)"
            if denominator_is_rows
            else f"SUM({numerator.column}) / SUM({denominator_name})"
        )
        if rule.multiply != 1.0:
            calculation += f" x {rule.multiply:g}"

        definitions.append(
            KPIDefinition(
                id=rule.id,
                name=rule.name,
                format=rule.format,
                calculation=calculation,
                why_it_matters=rule.why_it_matters,
                source_columns=[
                    c for c in (numerator.column, denominator_name) if c
                ],
                priority=rule.priority,
                higher_is_better=rule.higher_is_better,
                numerator=numerator.column,
                numerator_agg=rule.numerator_agg,
                denominator=denominator_name,
                denominator_agg=rule.denominator_agg,
                denominator_is_row_count=denominator_is_rows,
                multiply=rule.multiply,
            )
        )

    # -- 4. boolean flag rates --------------------------------------------
    flags = catalog.flag_candidates(profile)
    for rule in catalog.FLAG_RULES:
        match = catalog.find_column(profile, rule.column_tokens, candidates=flags)
        if match is None:
            continue
        definitions.append(
            KPIDefinition(
                id=rule.id,
                name=rule.name_template,
                format=ValueFormat.PERCENT,
                calculation=f"COUNT(*) WHERE {match.column} IS TRUE / COUNT(*) x 100",
                why_it_matters=rule.why_it_matters,
                source_columns=[match.column],
                priority=rule.priority,
                higher_is_better=rule.higher_is_better,
                flag_column=match.column,
            )
        )

    # -- 5. distinct counts for identifier columns -------------------------
    for col in profile.columns:
        if col.semantic_role != SemanticRole.IDENTIFIER:
            continue
        # A per-row identifier duplicates the record count; only entity ids
        # that repeat (customers, products) add information.
        if col.is_unique_key or col.cardinality_ratio > 0.95:
            continue
        definitions.append(
            KPIDefinition(
                id=f"distinct_{col.name}",
                name=f"Unique {humanize(col.name).replace(' Id', '').replace(' ID', '')}",
                format=ValueFormat.COUNT,
                calculation=f"COUNT(DISTINCT {col.name})",
                why_it_matters=(
                    f"How many distinct {humanize(col.name).lower()} values the "
                    "filtered rows cover."
                ),
                source_columns=[col.name],
                priority=62,
                measure=col.name,
                aggregation=Aggregation.COUNT_DISTINCT,
            )
        )

    # De-duplicate by id, keeping the highest priority definition.
    unique: dict[str, KPIDefinition] = {}
    for definition in definitions:
        existing = unique.get(definition.id)
        if existing is None or definition.priority > existing.priority:
            unique[definition.id] = definition

    ordered = sorted(unique.values(), key=lambda d: -d.priority)
    log.info(
        "Discovered %d candidate KPIs for %s (domain=%s)",
        len(ordered), profile.name, domain,
    )
    return ordered


def _is_cost_like(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in ("cost", "expense", "spend", "churn", "attrition", "defect", "loss")
    )


def _rank_measures(profile: DatasetProfile, measures: list[str]) -> list[str]:
    from ..analysis.eda import rank_measures

    return rank_measures(profile, measures)


# --------------------------------------------------------------------------
# LLM proposals
# --------------------------------------------------------------------------


def apply_llm_proposals(
    definitions: list[KPIDefinition],
    proposals: list[LLMKPIProposal],
    profile: DatasetProfile,
) -> list[KPIDefinition]:
    """Fold validated LLM KPI proposals into the deterministic set.

    A proposal is accepted only if every column it references exists and is
    numeric. Its *value* is still computed by `KPIDefinition.compute`, so a
    hallucinated number can never reach the dashboard — only a hallucinated
    column name, which is rejected here.
    """
    valid_measures = set(catalog.measure_candidates(profile))
    by_id = {d.id: d for d in definitions}
    accepted = 0

    for proposal in proposals:
        name = proposal.name.strip()
        if not name:
            continue
        kpi_id = name.lower().replace(" ", "_")[:60]

        if proposal.numerator_column and proposal.denominator_column:
            if (
                proposal.numerator_column not in valid_measures
                or proposal.denominator_column not in valid_measures
            ):
                log.debug("Rejected LLM KPI %s: unknown ratio columns", name)
                continue
            multiply = 100.0 if proposal.format == ValueFormat.PERCENT else 1.0
            definition = KPIDefinition(
                id=kpi_id,
                name=name,
                format=proposal.format,
                calculation=(
                    f"SUM({proposal.numerator_column}) / "
                    f"SUM({proposal.denominator_column})"
                    + (f" x {multiply:g}" if multiply != 1.0 else "")
                ),
                why_it_matters=proposal.why_it_matters
                or "Proposed by semantic analysis of this dataset.",
                source_columns=[
                    proposal.numerator_column,
                    proposal.denominator_column,
                ],
                priority=min(int(proposal.priority), 99),
                numerator=proposal.numerator_column,
                denominator=proposal.denominator_column,
                multiply=multiply,
                source=GenerationSource.AI,
            )
        elif proposal.measure_column:
            if proposal.measure_column not in valid_measures:
                log.debug("Rejected LLM KPI %s: unknown measure column", name)
                continue
            definition = KPIDefinition(
                id=kpi_id,
                name=name,
                format=proposal.format,
                calculation=(
                    f"{proposal.aggregation.value.upper()}"
                    f"({proposal.measure_column})"
                ),
                why_it_matters=proposal.why_it_matters
                or "Proposed by semantic analysis of this dataset.",
                source_columns=[proposal.measure_column],
                priority=min(int(proposal.priority), 99),
                measure=proposal.measure_column,
                aggregation=proposal.aggregation,
                source=GenerationSource.AI,
            )
        else:
            continue

        existing = by_id.get(definition.id)
        if existing is not None:
            # Keep the deterministic calculation but adopt the model's naming
            # and ranking, which are the parts it is actually good at.
            existing.name = definition.name
            existing.why_it_matters = definition.why_it_matters or existing.why_it_matters
            existing.priority = max(existing.priority, definition.priority)
            existing.source = GenerationSource.HYBRID
        else:
            by_id[definition.id] = definition
            accepted += 1

    log.info("Accepted %d new KPI proposals from the model", accepted)
    return sorted(by_id.values(), key=lambda d: -d.priority)


# --------------------------------------------------------------------------
# calculation
# --------------------------------------------------------------------------


def _previous_period_filters(
    profile: DatasetProfile, query: DatasetQuery, grain: TimeGrain
) -> tuple[list[FilterValue], list[FilterValue], str] | None:
    """Build filters isolating the latest complete period and the one before.

    Returns (current, previous, label) or None when the dataset has too little
    history for an honest comparison.
    """
    date_column = profile.primary_date_column
    if not date_column:
        return None
    try:
        series = query.time_series(
            date_column, None, Aggregation.COUNT, grain
        )
    except QueryError:
        return None

    series = series.dropna(subset=["period"]).sort_values("period")
    if len(series) < 3:
        return None

    counts = pd.to_numeric(series["row_count"], errors="coerce")
    # Drop a trailing partial period so the comparison is like-for-like.
    typical = float(counts.iloc[:-1].median())
    if typical > 0 and float(counts.iloc[-1]) < typical * 0.6:
        series = series.iloc[:-1]
    if len(series) < 2:
        return None

    current_start = pd.Timestamp(series["period"].iloc[-1])
    previous_start = pd.Timestamp(series["period"].iloc[-2])

    offsets = {
        TimeGrain.DAY: pd.DateOffset(days=1),
        TimeGrain.WEEK: pd.DateOffset(weeks=1),
        TimeGrain.MONTH: pd.DateOffset(months=1),
        TimeGrain.QUARTER: pd.DateOffset(months=3),
        TimeGrain.YEAR: pd.DateOffset(years=1),
    }
    offset = offsets.get(grain, pd.DateOffset(months=1))
    current_end = current_start + offset

    def window(start: pd.Timestamp, end: pd.Timestamp) -> list[FilterValue]:
        return [
            FilterValue(
                column=date_column,
                operator="between",
                value=[start.isoformat(), (end - pd.Timedelta(microseconds=1)).isoformat()],
            )
        ]

    period_word = {
        TimeGrain.DAY: "day",
        TimeGrain.WEEK: "week",
        TimeGrain.MONTH: "month",
        TimeGrain.QUARTER: "quarter",
        TimeGrain.YEAR: "year",
    }.get(grain, "period")
    # Name the date column driving the comparison. In a snapshot dataset the
    # periods are cohorts (employees *hired* that quarter), not a running
    # total, and the label has to say so rather than imply a headcount trend.
    label = f"vs previous {period_word} (by {date_column})"

    return (
        window(current_start, current_end),
        window(previous_start, current_start),
        label,
    )


def calculate_kpis(
    definitions: list[KPIDefinition],
    query: DatasetQuery,
    profile: DatasetProfile,
    *,
    filters: list[FilterValue] | None = None,
    include_comparison: bool = True,
    limit: int = MAX_KPIS,
) -> list[KPI]:
    """Compute values (and period-over-period deltas) for KPI definitions."""
    filters = filters or []
    results: list[KPI] = []

    comparison_windows = None
    if include_comparison and profile.primary_date_column and not filters:
        date_profile = profile.column(profile.primary_date_column)
        grain_name = (
            date_profile.datetime.suggested_grain
            if date_profile and date_profile.datetime
            else "month"
        )
        try:
            grain = TimeGrain(grain_name)
        except ValueError:
            grain = TimeGrain.MONTH
        comparison_windows = _previous_period_filters(profile, query, grain)

    for definition in definitions:
        value = definition.compute(query, filters)
        if value is None:
            continue

        comparison = None
        if comparison_windows is not None:
            current_filters, previous_filters, label = comparison_windows
            current = definition.compute(query, current_filters)
            previous = definition.compute(query, previous_filters)
            if current is not None and previous:
                change = current - previous
                change_pct = change / abs(previous) * 100
                direction = "up" if change > 0 else ("down" if change < 0 else "flat")
                comparison = KPIComparison(
                    previous_value=round(previous, 4),
                    change=round(change, 4),
                    change_pct=round(change_pct, 2),
                    direction=direction,
                    period_label=label,
                    is_favorable=(
                        None
                        if direction == "flat"
                        else (direction == "up") == definition.higher_is_better
                    ),
                )

        results.append(
            KPI(
                id=definition.id,
                name=definition.name,
                value=round(value, 4),
                formatted_value=format_value(value, definition.format, definition.unit),
                format=definition.format,
                unit=definition.unit,
                calculation=definition.calculation,
                why_it_matters=definition.why_it_matters,
                source_columns=definition.source_columns,
                comparison=comparison,
                priority=definition.priority,
                source=definition.source,
            )
        )
        if len(results) >= limit:
            break

    return results
