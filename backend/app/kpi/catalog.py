"""Rule catalogue for KPI discovery.

There is no fixed list of KPIs. Instead there is a list of *patterns* — "if
this dataset has a profit column and a revenue column, then profit margin is
a meaningful KPI" — which are matched against whatever columns the dataset
actually has. A sales file and an HR file therefore produce entirely different
KPI sets from the same code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..profiling.semantics import match_strength, normalize
from ..schemas.enums import Aggregation, SemanticRole, ValueFormat
from ..schemas.profile import DatasetProfile


@dataclass(frozen=True)
class RatioRule:
    """A KPI defined as one aggregate divided by another."""

    id: str
    name: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    format: ValueFormat
    why_it_matters: str
    priority: int = 50
    multiply: float = 1.0
    numerator_agg: Aggregation = Aggregation.SUM
    denominator_agg: Aggregation = Aggregation.SUM
    higher_is_better: bool = True
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlagRateRule:
    """A KPI defined as the share of rows where a boolean column is true."""

    id: str
    name_template: str
    column_tokens: tuple[str, ...]
    why_it_matters: str
    priority: int = 55
    higher_is_better: bool = False


# --------------------------------------------------------------------------
# Ratio KPIs. Token lists are matched against the dataset's measure columns.
# --------------------------------------------------------------------------

RATIO_RULES: tuple[RatioRule, ...] = (
    RatioRule(
        id="profit_margin",
        name="Profit Margin",
        numerator=("profit", "net_profit", "gross_profit", "margin"),
        denominator=("revenue", "sales", "net_sales", "gmv", "amount"),
        format=ValueFormat.PERCENT,
        multiply=100.0,
        why_it_matters=(
            "Shows how much of every unit of revenue is retained as profit. "
            "Revenue growth with a falling margin usually signals rising costs."
        ),
        priority=92,
    ),
    RatioRule(
        id="average_order_value",
        name="Average Order Value",
        numerator=("revenue", "sales", "amount", "total"),
        denominator=("__row_count__",),
        format=ValueFormat.CURRENCY,
        why_it_matters=(
            "Average revenue per order. Rising AOV means customers are buying "
            "more or higher-priced items per transaction."
        ),
        priority=78,
        domains=("sales", "ecommerce"),
    ),
    RatioRule(
        id="conversion_rate",
        name="Conversion Rate",
        numerator=("conversions", "leads", "signups", "orders"),
        denominator=("clicks", "sessions", "visits", "impressions"),
        format=ValueFormat.PERCENT,
        multiply=100.0,
        why_it_matters=(
            "The share of engaged users who complete the target action — the "
            "clearest measure of funnel efficiency."
        ),
        priority=90,
    ),
    RatioRule(
        id="click_through_rate",
        name="Click-Through Rate",
        numerator=("clicks",),
        denominator=("impressions", "views"),
        format=ValueFormat.PERCENT,
        multiply=100.0,
        why_it_matters="How compelling the creative is to the audience it reaches.",
        priority=76,
    ),
    RatioRule(
        id="cost_per_click",
        name="Cost per Click",
        numerator=("spend", "cost", "budget"),
        denominator=("clicks",),
        format=ValueFormat.CURRENCY,
        why_it_matters="What the channel charges for each engaged visitor.",
        priority=70,
        higher_is_better=False,
    ),
    RatioRule(
        id="cost_per_acquisition",
        name="Cost per Acquisition",
        numerator=("spend", "cost", "budget"),
        denominator=("conversions", "leads", "signups"),
        format=ValueFormat.CURRENCY,
        why_it_matters=(
            "What it costs to win one customer. Compare against customer value "
            "to judge whether growth is profitable."
        ),
        priority=86,
        higher_is_better=False,
    ),
    RatioRule(
        id="return_on_ad_spend",
        name="Return on Ad Spend",
        numerator=("revenue", "sales"),
        denominator=("spend", "cost", "budget"),
        format=ValueFormat.DECIMAL,
        why_it_matters=(
            "Revenue generated per unit of spend. Below 1.0 means the activity "
            "loses money before other costs."
        ),
        priority=88,
        domains=("marketing",),
    ),
    RatioRule(
        id="units_per_order",
        name="Units per Order",
        numerator=("quantity", "units", "items"),
        denominator=("__row_count__",),
        format=ValueFormat.DECIMAL,
        why_it_matters="Basket size — how many items a typical order contains.",
        priority=60,
        domains=("sales", "ecommerce"),
    ),
    RatioRule(
        id="effective_tax_rate",
        name="Effective Tax Rate",
        numerator=("tax", "tax_amount"),
        denominator=("amount", "revenue", "gross"),
        format=ValueFormat.PERCENT,
        multiply=100.0,
        why_it_matters="Share of transaction value absorbed by tax.",
        priority=55,
        domains=("finance",),
        higher_is_better=False,
    ),
)


# --------------------------------------------------------------------------
# Boolean-flag rate KPIs.
# --------------------------------------------------------------------------

FLAG_RULES: tuple[FlagRateRule, ...] = (
    FlagRateRule(
        id="attrition_rate",
        name_template="Attrition Rate",
        column_tokens=("left", "left_company", "attrition", "terminated", "resigned", "churn"),
        why_it_matters=(
            "Share of people who have left. Sustained attrition above the "
            "organisation's norm is expensive to replace."
        ),
        priority=94,
    ),
    FlagRateRule(
        id="return_rate",
        name_template="Return Rate",
        column_tokens=("returned", "refund", "returns", "cancelled", "canceled"),
        why_it_matters=(
            "Share of orders sent back. High return rates erode margin and "
            "often point to product or expectation problems."
        ),
        priority=80,
    ),
    FlagRateRule(
        id="active_rate",
        name_template="Active Rate",
        column_tokens=("active", "is_active", "enabled", "subscribed"),
        why_it_matters="Share of records currently in an active state.",
        priority=58,
        higher_is_better=True,
    ),
)


# Domain-specific labels for the "how many rows are there" KPI.
RECORD_COUNT_LABELS: dict[str, tuple[str, str]] = {
    "sales": ("Total Orders", "Number of orders in the dataset."),
    "ecommerce": ("Total Orders", "Number of orders placed."),
    "finance": ("Total Transactions", "Number of financial transactions recorded."),
    "hr": ("Headcount", "Number of employees in the dataset."),
    "marketing": ("Total Campaigns", "Number of campaigns measured."),
    "operations": ("Total Records", "Number of operational events recorded."),
    "customer": ("Total Customers", "Number of customer records."),
    "healthcare": ("Total Encounters", "Number of patient encounters."),
    "education": ("Total Enrollments", "Number of enrollment records."),
    "general": ("Total Records", "Number of rows in the dataset."),
}


@dataclass
class ColumnMatch:
    column: str
    score: float
    token: str


def find_column(
    profile: DatasetProfile,
    tokens: tuple[str, ...],
    *,
    candidates: list[str],
) -> ColumnMatch | None:
    """Find the candidate column whose name best matches any of `tokens`."""
    best: ColumnMatch | None = None
    lexicon = set(tokens)
    for name in candidates:
        score, token = match_strength(name, lexicon)
        if score <= 0 or token is None:
            continue
        # Prefer the shortest matching name: `revenue` beats `revenue_forecast`.
        adjusted = score - len(normalize(name)) * 0.001
        if best is None or adjusted > best.score:
            best = ColumnMatch(column=name, score=adjusted, token=token)
    return best


def measure_candidates(profile: DatasetProfile) -> list[str]:
    """Numeric columns that can legitimately be aggregated."""
    return [
        c.name
        for c in profile.columns
        if c.name in profile.numeric_columns
        and c.semantic_role != SemanticRole.IDENTIFIER
        and not c.is_constant
    ]


def flag_candidates(profile: DatasetProfile) -> list[str]:
    return [c.name for c in profile.columns if c.name in profile.boolean_columns]


def record_label(domain: str | None) -> tuple[str, str]:
    return RECORD_COUNT_LABELS.get(domain or "general", RECORD_COUNT_LABELS["general"])
