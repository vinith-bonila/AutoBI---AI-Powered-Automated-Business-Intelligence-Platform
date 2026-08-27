"""Semantic role inference.

Column *names* are a hint, never proof. Every rule here combines a name signal
with evidence from the actual values (cardinality, range, dtype, distribution)
and returns a confidence score plus the evidence that produced it, so the UI
can explain why a column was classified the way it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from ..schemas.enums import InferredType, SemanticRole
from ..utils import coercion

# --------------------------------------------------------------------------
# Name lexicons. Matched as whole-ish tokens against a normalised column name.
# --------------------------------------------------------------------------

CURRENCY_TOKENS = {
    "revenue", "sales", "price", "cost", "amount", "profit", "salary", "budget",
    "spend", "spending", "income", "expense", "expenses", "fee", "fees", "payment",
    "payments", "value", "gmv", "arr", "mrr", "wage", "compensation", "pay",
    "billing", "invoice", "charge", "premium", "balance", "deposit", "withdrawal",
    "turnover", "margin_value", "subtotal", "cogs",
    "ltv", "cac", "cpc", "cpa", "cpl", "aov", "usd", "eur", "gbp", "revenues",
}

QUANTITY_TOKENS = {
    "quantity", "qty", "units", "count", "orders", "items", "sold", "clicks",
    "impressions", "visits", "sessions", "leads", "headcount", "employees",
    "customers", "users", "subscribers", "views", "downloads", "shipments",
    "transactions", "returns", "tickets", "calls", "signups", "conversions",
    "stock", "inventory", "volume", "num",
}

PERCENT_TOKENS = {
    "pct", "percent", "percentage", "rate", "margin", "ratio", "share",
    "conversion", "ctr", "cvr", "churn", "attrition", "utilization", "occupancy",
    "growth", "discount", "completion", "satisfaction", "accuracy", "roi", "roas",
}

GEO_TOKENS = {
    "country", "region", "state", "city", "province", "zip", "zipcode", "postal",
    "postcode", "location", "territory", "market", "continent", "district",
    "county", "area", "site", "branch", "store_location", "geo", "address",
}

IDENTIFIER_TOKENS = {
    "id", "uuid", "guid", "key", "code", "sku", "reference", "ref", "number",
    "no", "identifier", "hash", "token", "account", "order_id", "invoice_no",
}

DEMOGRAPHIC_TOKENS = {
    "age", "gender", "sex", "tenure", "seniority", "experience", "education",
    "marital", "ethnicity", "nationality", "birth", "dob", "generation",
}

TIME_TOKENS = {"date", "time", "timestamp", "day", "month", "year", "week", "quarter"}

TEXT_TOKENS = {
    "description", "comment", "comments", "notes", "note", "feedback", "review",
    "message", "summary", "text", "body", "title", "subject", "url", "email",
    "address", "reason",
}

_ID_SUFFIX_RE = re.compile(r"(^|_)(id|ids|key|code|no|num|uuid|guid)$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)

DOMAIN_LEXICON: dict[str, set[str]] = {
    "sales": {
        "revenue", "sales", "order", "orders", "profit", "discount", "quantity",
        "unit_price", "salesperson", "deal", "pipeline", "quota", "territory",
    },
    "ecommerce": {
        "product", "sku", "cart", "checkout", "shipping", "order", "category",
        "basket", "customer", "return", "coupon", "payment_method", "delivery",
    },
    "finance": {
        "transaction", "account", "balance", "debit", "credit", "ledger",
        "expense", "budget", "invoice", "payment", "interest", "asset",
        "liability", "portfolio", "merchant", "currency",
    },
    "hr": {
        "employee", "department", "salary", "hire", "attrition", "tenure",
        "manager", "job_title", "performance", "headcount", "termination",
        "position", "leave", "recruitment", "resigned", "role",
    },
    "marketing": {
        "campaign", "channel", "impressions", "clicks", "ctr", "cpc", "leads",
        "conversion", "spend", "roi", "roas", "audience", "ad", "creative",
        "utm", "email_open", "engagement",
    },
    "operations": {
        "shipment", "warehouse", "inventory", "supplier", "logistics",
        "downtime", "throughput", "defect", "production", "machine", "batch",
        "delivery_time", "sla", "capacity", "utilization",
    },
    "customer": {
        "customer", "churn", "satisfaction", "nps", "support", "ticket",
        "subscription", "retention", "segment", "loyalty", "lifetime_value",
    },
    "healthcare": {
        "patient", "diagnosis", "treatment", "admission", "discharge", "doctor",
        "hospital", "medication", "clinic", "readmission",
    },
    "education": {
        "student", "course", "grade", "enrollment", "teacher", "school",
        "attendance", "exam", "score", "semester",
    },
}


@dataclass
class RoleVerdict:
    role: SemanticRole
    confidence: float
    evidence: list[str]


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def tokens(name: str) -> set[str]:
    norm = normalize(name)
    parts = set(norm.split("_"))
    parts.add(norm)
    # Also add adjacent bigrams so `unit_price` matches `unit_price`.
    words = norm.split("_")
    for i in range(len(words) - 1):
        parts.add(f"{words[i]}_{words[i + 1]}")
    return {p for p in parts if p}


def match_strength(name: str, lexicon: set[str]) -> tuple[float, str | None]:
    """Score a name against a lexicon.

    An exact token match (`orders` in `total_orders`) scores higher than a
    substring match (`conversion` inside `conversions`), so a specific word
    always beats an incidental one. The number of distinct hits breaks ties.
    """
    tok = tokens(name)
    hits = tok & lexicon
    if hits:
        return (2.0 + 0.1 * (len(hits) - 1), sorted(hits)[0])
    norm = normalize(name).replace("_", "")
    for word in sorted(lexicon, key=len, reverse=True):
        if len(word) >= 5 and word.replace("_", "") in norm:
            return (1.0, word)
    return (0.0, None)


def _matches(name: str, lexicon: set[str]) -> str | None:
    return match_strength(name, lexicon)[1]


def infer_role(
    *,
    name: str,
    series: pd.Series,
    inferred_type: InferredType,
    unique: int,
    non_null_count: int,
    numeric_min: float | None = None,
    numeric_max: float | None = None,
) -> RoleVerdict:
    """Decide the business meaning of a column."""
    evidence: list[str] = []
    cardinality_ratio = (unique / non_null_count) if non_null_count else 0.0

    if inferred_type == InferredType.EMPTY:
        return RoleVerdict(SemanticRole.UNKNOWN, 1.0, ["column is entirely empty"])

    # --- time -------------------------------------------------------------
    if inferred_type == InferredType.DATETIME:
        return RoleVerdict(SemanticRole.TIME, 0.98, ["values parse as dates"])

    # --- boolean flags ----------------------------------------------------
    if inferred_type == InferredType.BOOLEAN:
        return RoleVerdict(SemanticRole.FLAG, 0.95, ["two-state boolean values"])

    # --- identifiers ------------------------------------------------------
    id_name_hit = _matches(name, IDENTIFIER_TOKENS) or (
        "id-like suffix" if _ID_SUFFIX_RE.search(normalize(name)) else None
    )
    sample = coercion.non_null(series).head(200).astype(str)
    looks_uuid = not sample.empty and float(sample.str.match(_UUID_RE).mean()) > 0.8
    near_unique = cardinality_ratio > 0.9 and unique > 20

    if looks_uuid:
        return RoleVerdict(SemanticRole.IDENTIFIER, 0.99, ["values are UUIDs"])
    if id_name_hit and cardinality_ratio > 0.3:
        evidence.append(f"name matches `{id_name_hit}`")
        evidence.append(f"{cardinality_ratio:.0%} distinct values")
        return RoleVerdict(SemanticRole.IDENTIFIER, 0.9, evidence)
    if near_unique and inferred_type in (InferredType.TEXT, InferredType.CATEGORICAL):
        return RoleVerdict(
            SemanticRole.IDENTIFIER,
            0.7,
            [f"{cardinality_ratio:.0%} distinct values across {non_null_count:,} rows"],
        )
    if near_unique and inferred_type == InferredType.NUMERIC and id_name_hit:
        return RoleVerdict(
            SemanticRole.IDENTIFIER, 0.85,
            [f"name matches `{id_name_hit}`", "values are near-unique integers"],
        )

    # --- numeric roles ----------------------------------------------------
    if inferred_type == InferredType.NUMERIC:
        if coercion.has_percent_literal(series):
            return RoleVerdict(
                SemanticRole.PERCENTAGE, 0.95, ["values are written with `%`"]
            )
        if coercion.has_currency_literal(series):
            return RoleVerdict(
                SemanticRole.CURRENCY, 0.95, ["values carry a currency symbol"]
            )

        # Rank every candidate lexicon and let the strongest name signal win,
        # so `conversions` reads as a quantity rather than a conversion *rate*.
        ranked = sorted(
            (
                (match_strength(name, PERCENT_TOKENS), SemanticRole.PERCENTAGE),
                (match_strength(name, CURRENCY_TOKENS), SemanticRole.CURRENCY),
                (match_strength(name, QUANTITY_TOKENS), SemanticRole.QUANTITY),
                (match_strength(name, DEMOGRAPHIC_TOKENS), SemanticRole.DEMOGRAPHIC),
            ),
            key=lambda item: item[0][0],
            reverse=True,
        )
        (strength, hit_word), best_role = ranked[0]

        if strength > 0 and hit_word:
            if best_role == SemanticRole.PERCENTAGE:
                # A 1-5 rating matches words like `satisfaction` but is really
                # an ordinal scale, not a percentage.
                looks_like_scale = (
                    unique <= 12
                    and numeric_max is not None
                    and numeric_max <= 10
                )
                if looks_like_scale:
                    return RoleVerdict(
                        SemanticRole.DIMENSION,
                        0.7,
                        [
                            f"only {unique} distinct values up to {numeric_max:g}",
                            "reads as an ordinal rating scale, not a percentage",
                        ],
                    )
                in_pct_range = (
                    numeric_min is not None
                    and numeric_max is not None
                    and -100.0 <= numeric_min
                    and numeric_max <= 100.0
                )
                in_unit_range = (
                    numeric_min is not None
                    and numeric_max is not None
                    and -1.5 <= numeric_min
                    and numeric_max <= 1.5
                )
                if in_pct_range or in_unit_range:
                    return RoleVerdict(
                        SemanticRole.PERCENTAGE,
                        0.9,
                        [f"name matches `{hit_word}`", "values sit inside a rate range"],
                    )
                return RoleVerdict(
                    SemanticRole.RATIO,
                    0.6,
                    [f"name matches `{hit_word}`", "values exceed a rate range"],
                )
            confidence = 0.85 if strength >= 2.0 else 0.7
            return RoleVerdict(best_role, confidence, [f"name matches `{hit_word}`"])

        year_like = (
            numeric_min is not None
            and numeric_max is not None
            and 1900 <= numeric_min
            and numeric_max <= 2100
            and unique < 200
        )
        if year_like and _matches(name, TIME_TOKENS):
            return RoleVerdict(
                SemanticRole.TIME, 0.75, ["integer values inside a year range"]
            )

        # Low-cardinality integers behave as dimensions (rating 1-5, priority).
        if unique <= 12 and cardinality_ratio < 0.05 and non_null_count > 100:
            return RoleVerdict(
                SemanticRole.DIMENSION,
                0.6,
                [f"only {unique} distinct numeric values — behaves like a category"],
            )

        return RoleVerdict(
            SemanticRole.MEASURE, 0.65, ["continuous numeric values, no name signal"]
        )

    # --- text / categorical ----------------------------------------------
    if not sample.empty and float(sample.str.match(_EMAIL_RE).mean()) > 0.8:
        return RoleVerdict(SemanticRole.IDENTIFIER, 0.9, ["values are email addresses"])

    geo_hit = _matches(name, GEO_TOKENS)
    if geo_hit and inferred_type == InferredType.CATEGORICAL:
        return RoleVerdict(SemanticRole.GEO, 0.85, [f"name matches `{geo_hit}`"])

    demo_hit = _matches(name, DEMOGRAPHIC_TOKENS)
    if demo_hit and inferred_type == InferredType.CATEGORICAL:
        return RoleVerdict(
            SemanticRole.DEMOGRAPHIC, 0.8, [f"name matches `{demo_hit}`"]
        )

    if inferred_type == InferredType.TEXT:
        text_hit = _matches(name, TEXT_TOKENS)
        ev = [f"name matches `{text_hit}`"] if text_hit else ["long, high-variety text"]
        return RoleVerdict(SemanticRole.TEXT, 0.7, ev)

    return RoleVerdict(
        SemanticRole.DIMENSION,
        0.7,
        [f"{unique} distinct labels — usable as a grouping dimension"],
    )


def guess_domain(column_names: list[str]) -> tuple[str, list[str]]:
    """Score the dataset against domain lexicons using column names."""
    all_tokens: set[str] = set()
    for name in column_names:
        all_tokens |= tokens(name)

    scores: dict[str, list[str]] = {}
    for domain, lexicon in DOMAIN_LEXICON.items():
        hits = sorted(all_tokens & lexicon)
        # Substring pass for concatenated headers.
        if not hits:
            joined = "_".join(sorted(all_tokens))
            hits = sorted({w for w in lexicon if len(w) >= 6 and w in joined})
        if hits:
            scores[domain] = hits

    if not scores:
        return "general", []

    best = max(scores.items(), key=lambda kv: (len(kv[1]), -len(kv[0])))
    domain, hits = best
    if len(hits) < 2:
        # One weak hit is not enough to commit to a domain.
        return "general", [f"{d}: {', '.join(h)}" for d, h in scores.items()]
    signals = [f"{domain}: {', '.join(hits[:6])}"]
    for other, other_hits in sorted(
        scores.items(), key=lambda kv: -len(kv[1])
    ):
        if other != domain and len(other_hits) >= 2:
            signals.append(f"{other}: {', '.join(other_hits[:4])}")
    return domain, signals[:4]
