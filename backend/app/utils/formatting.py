"""Human-readable formatting of metric values."""

from __future__ import annotations

from ..schemas.enums import ValueFormat

_UNITS = [(1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")]


def compact_number(value: float, decimals: int = 1) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    for threshold, suffix in _UNITS:
        if v >= threshold:
            scaled = v / threshold
            text = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    if v >= 100 or v == int(v):
        return f"{sign}{v:,.0f}"
    return f"{sign}{v:,.2f}"


def format_value(
    value: float | None,
    fmt: ValueFormat,
    unit: str | None = None,
) -> str:
    if value is None:
        return "—"
    if fmt == ValueFormat.CURRENCY:
        symbol = unit or "$"
        return f"{symbol}{compact_number(value)}"
    if fmt == ValueFormat.PERCENT:
        return f"{value:,.1f}%"
    if fmt == ValueFormat.COUNT:
        return f"{value:,.0f}"
    if fmt == ValueFormat.DECIMAL:
        return f"{value:,.2f}"
    if fmt == ValueFormat.DURATION_DAYS:
        if abs(value) >= 365:
            return f"{value / 365:.1f} yrs"
        return f"{value:,.0f} days"
    return compact_number(value)


def format_pct_change(pct: float | None) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def humanize(name: str) -> str:
    """`total_revenue_usd` -> `Total Revenue USD`."""
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return name
    words = []
    for word in cleaned.split():
        if word.isupper() and len(word) <= 4:
            words.append(word)
        elif word.lower() in ("id", "usd", "eur", "gbp", "roi", "kpi", "ctr", "cpc"):
            words.append(word.upper())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)
