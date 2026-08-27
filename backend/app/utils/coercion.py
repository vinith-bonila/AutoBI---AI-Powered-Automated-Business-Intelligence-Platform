"""Value coercion primitives.

Both the profiler (which only *inspects*) and the cleaner (which *commits*)
use these, so detection and transformation can never disagree.

Every `try_*` function returns the converted series plus the ratio of non-null
inputs it successfully converted. Callers decide, via a threshold, whether the
conversion is safe enough to apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

CURRENCY_SYMBOLS = "$€£¥₹₽₩₪"
_CURRENCY_RE = re.compile(rf"[{re.escape(CURRENCY_SYMBOLS)}]")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
_SPACE_THOUSANDS_RE = re.compile(r"(?<=\d)[\s ](?=\d{3}(?:\D|$))")
_PARENS_NEG_RE = re.compile(r"^\((.*)\)$")
_PARENS_DETECT_RE = re.compile(r"^\(.*\)$")
_TRAILING_UNIT_RE = re.compile(
    r"\s*(?:usd|eur|gbp|inr|units?|pcs|kg|hrs?|hours?)\.?$", re.I
)
_DATE_HINT_RE = re.compile(
    r"[-/:]|\d{1,2}\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I
)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_COMPACT_DATE_RE = re.compile(r"^(?:19|20)\d{6}$")

TRUE_TOKENS = {"true", "t", "yes", "y", "1", "on", "active", "enabled"}
FALSE_TOKENS = {"false", "f", "no", "n", "0", "off", "inactive", "disabled"}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%Y-%m",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y%m%d",
)


@dataclass
class CoercionResult:
    series: pd.Series
    success_ratio: float
    detected: bool
    notes: list[str]
    metadata: dict[str, object]

    @property
    def converted_count(self) -> int:
        return int(self.series.notna().sum())


def _as_str(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def non_null(series: pd.Series) -> pd.Series:
    """Non-null, non-blank values, as strings when the source is text."""
    s = series[series.notna()]
    if s.dtype == object or str(s.dtype) == "string":
        s = _as_str(s)
        s = s[(s != "") & s.notna()]
    return s


# --------------------------------------------------------------------------
# numeric
# --------------------------------------------------------------------------


def clean_numeric_strings(series: pd.Series) -> tuple[pd.Series, dict[str, bool]]:
    """Strip currency symbols, thousands separators, percent signs and units."""
    s = _as_str(series)
    flags = {"currency": False, "percent": False, "thousands": False, "parens": False}

    if s.str.contains(_CURRENCY_RE, na=False).any():
        flags["currency"] = True
        s = s.str.replace(_CURRENCY_RE, "", regex=True)
    if s.str.contains(r"%$", na=False, regex=True).any():
        flags["percent"] = True
        s = s.str.replace(r"%$", "", regex=True)
    if s.str.contains(_THOUSANDS_RE, na=False).any():
        flags["thousands"] = True
    s = s.str.replace(_THOUSANDS_RE, "", regex=True)
    s = s.str.replace(_SPACE_THOUSANDS_RE, "", regex=True)
    if s.str.contains(_PARENS_DETECT_RE, na=False).any():
        flags["parens"] = True
        s = s.str.replace(_PARENS_NEG_RE, r"-\1", regex=True)
    s = s.str.replace(_TRAILING_UNIT_RE, "", regex=True)
    s = s.str.replace("−", "-", regex=False)  # unicode minus
    s = s.str.replace(r"^\+", "", regex=True)
    return s.str.strip(), flags


def try_numeric(series: pd.Series) -> CoercionResult:
    """Attempt to interpret a column as numeric."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return CoercionResult(
            series=pd.to_numeric(series, errors="coerce"),
            success_ratio=1.0,
            detected=True,
            notes=[],
            metadata={},
        )

    source = non_null(series)
    if source.empty:
        return CoercionResult(
            pd.Series(np.nan, index=series.index, dtype="float64"), 0.0, False, [], {}
        )

    cleaned, flags = clean_numeric_strings(series)
    converted = pd.to_numeric(cleaned, errors="coerce")
    ratio = float(converted.loc[source.index].notna().mean()) if len(source) else 0.0

    notes: list[str] = []
    if flags["currency"]:
        notes.append("currency symbols removed")
    if flags["thousands"]:
        notes.append("thousands separators removed")
    if flags["percent"]:
        notes.append("percent signs removed")
    if flags["parens"]:
        notes.append("parenthesised negatives converted")

    return CoercionResult(
        series=converted,
        success_ratio=ratio,
        detected=ratio >= 0.8,
        notes=notes,
        metadata=flags,
    )


# --------------------------------------------------------------------------
# datetime
# --------------------------------------------------------------------------


def looks_like_dates(series: pd.Series, column_name: str = "") -> bool:
    """Cheap gate so numeric IDs are never handed to the date parser."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    sample = non_null(series).head(200)
    if sample.empty:
        return False
    text = sample.astype(str)
    with_hints = float(text.str.contains(_DATE_HINT_RE, na=False).mean())
    has_year = float(text.str.contains(_YEAR_RE, na=False).mean())
    if with_hints >= 0.7 and has_year >= 0.5:
        return True
    if float(text.str.match(_COMPACT_DATE_RE).mean()) >= 0.9:
        return True
    name = column_name.lower()
    if any(t in name for t in ("date", "time", "day", "month", "year", "_at", "_on")):
        return with_hints >= 0.3 or float(text.str.match(_COMPACT_DATE_RE).mean()) >= 0.5
    return False


def try_datetime(series: pd.Series, column_name: str = "") -> CoercionResult:
    """Parse a column as datetimes, preferring explicit formats."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return CoercionResult(series, 1.0, True, [], {"format": "native"})

    empty = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    source = non_null(series)
    if source.empty or not looks_like_dates(series, column_name):
        return CoercionResult(empty, 0.0, False, [], {})

    text = _as_str(series)
    probe = text.loc[source.index].head(500)
    best_ratio, best_format = 0.0, None

    for fmt in DATE_FORMATS:
        try:
            parsed = pd.to_datetime(probe, format=fmt, errors="coerce")
        except (ValueError, TypeError):
            continue
        ratio = float(parsed.notna().mean())
        if ratio > best_ratio:
            best_ratio, best_format = ratio, fmt
        if ratio >= 0.99:
            break

    best_series: pd.Series | None = None
    formats_used: list[str] = []

    if best_format and best_ratio >= 0.8:
        best_series = pd.to_datetime(text, format=best_format, errors="coerce")
        formats_used.append(best_format)
        # A single format is rarely enough: exports frequently mix layouts
        # (an ISO date for most rows, US-style for the rest). Sweeping the
        # remaining formats over just the leftovers recovers those rows
        # instead of discarding them as missing.
        best_series, extra = _fill_remaining_formats(
            best_series, text, source.index, skip=best_format
        )
        formats_used.extend(extra)
        best_ratio = float(best_series.loc[source.index].notna().mean())
    else:
        for kwargs in ({"format": "ISO8601"}, {"format": "mixed", "dayfirst": False}):
            try:
                candidate = pd.to_datetime(text, errors="coerce", **kwargs)
            except (ValueError, TypeError):
                continue
            ratio = float(candidate.loc[source.index].notna().mean())
            if ratio > best_ratio:
                best_series, best_ratio = candidate, ratio
                best_format = str(kwargs)
                formats_used = [best_format]

    if best_series is None:
        return CoercionResult(empty, 0.0, False, [], {})

    # Reject absurd parses (year 1, year 3000) that mean it was not a date.
    valid = best_series.dropna()
    if not valid.empty:
        years = valid.dt.year
        plausible = float(((years >= 1900) & (years <= 2100)).mean())
        if plausible < 0.8:
            return CoercionResult(empty, 0.0, False, ["implausible year range"], {})

    if len(formats_used) > 1:
        notes = [f"parsed with mixed formats: {', '.join(formats_used)}"]
    elif best_format:
        notes = [f"parsed with {best_format}"]
    else:
        notes = []

    return CoercionResult(
        series=best_series,
        success_ratio=best_ratio,
        detected=best_ratio >= 0.8,
        notes=notes,
        metadata={"format": best_format, "formats": formats_used},
    )


def _fill_remaining_formats(
    parsed: pd.Series,
    text: pd.Series,
    source_index: pd.Index,
    *,
    skip: str,
) -> tuple[pd.Series, list[str]]:
    """Parse values the primary format missed, using the other known layouts.

    Only rows still unparsed are touched, so a format that happens to match a
    handful of rows can never overwrite a confident primary parse.
    """
    extra_formats: list[str] = []
    remaining = source_index[parsed.loc[source_index].isna()]
    if remaining.empty:
        return parsed, extra_formats

    while not remaining.empty:
        subset = text.loc[remaining]
        # Choose the format that explains the most leftover rows rather than
        # the first one that explains any. `03/06/2024` parses under both
        # %d/%m/%Y and %m/%d/%Y, and only the format that covers the whole
        # remainder is the one the file actually uses.
        best_fmt: str | None = None
        best_candidate: pd.Series | None = None
        best_filled = 0

        for fmt in DATE_FORMATS:
            if fmt == skip or fmt in extra_formats:
                continue
            try:
                candidate = pd.to_datetime(subset, format=fmt, errors="coerce")
            except (ValueError, TypeError):
                continue
            filled = int(candidate.notna().sum())
            if filled > best_filled:
                best_fmt, best_candidate, best_filled = fmt, candidate, filled

        if best_fmt is None or best_candidate is None or not best_filled:
            break

        mask = best_candidate.notna()
        parsed.loc[remaining[mask]] = best_candidate[mask]
        extra_formats.append(best_fmt)
        remaining = remaining[~mask]

    # Anything still unparsed gets one flexible attempt before being conceded.
    if not remaining.empty:
        try:
            candidate = pd.to_datetime(
                text.loc[remaining], format="mixed", errors="coerce"
            )
        except (ValueError, TypeError):
            candidate = None
        if candidate is not None and candidate.notna().any():
            filled = candidate.notna()
            parsed.loc[remaining[filled]] = candidate[filled]
            extra_formats.append("mixed")

    return parsed, extra_formats


# --------------------------------------------------------------------------
# boolean
# --------------------------------------------------------------------------


def try_boolean(series: pd.Series) -> CoercionResult:
    """Detect yes/no, true/false, y/n and on/off columns."""
    if pd.api.types.is_bool_dtype(series):
        return CoercionResult(series, 1.0, True, [], {})

    empty = pd.Series(pd.NA, index=series.index, dtype="boolean")
    source = non_null(series)
    if source.empty:
        return CoercionResult(empty, 0.0, False, [], {})

    lowered = source.astype(str).str.lower().str.strip()
    distinct = set(lowered.unique())
    if len(distinct) > 4 or not distinct.issubset(TRUE_TOKENS | FALSE_TOKENS):
        return CoercionResult(empty, 0.0, False, [], {})

    mapped = (
        _as_str(series)
        .str.lower()
        .map(
            lambda v: True
            if v in TRUE_TOKENS
            else (False if v in FALSE_TOKENS else None)
        )
        .astype("boolean")
    )
    ratio = float(mapped.loc[source.index].notna().mean())
    return CoercionResult(
        series=mapped,
        success_ratio=ratio,
        detected=ratio >= 0.95,
        notes=[],
        metadata={"tokens": sorted(distinct)},
    )


def has_percent_literal(series: pd.Series) -> bool:
    """True when the raw values are literally percent-formatted (`12.5%`)."""
    source = non_null(series)
    if source.empty:
        return False
    return float(source.astype(str).str.contains(r"%$", na=False).mean()) >= 0.8


def has_currency_literal(series: pd.Series) -> bool:
    source = non_null(series)
    if source.empty:
        return False
    return float(source.astype(str).str.contains(_CURRENCY_RE, na=False).mean()) >= 0.5


def dominant_decimals(series: pd.Series) -> int:
    """Typical number of decimal places, used to pick display precision."""
    sample = non_null(series).head(500).astype(str)
    if sample.empty:
        return 0
    decimals = sample.str.extract(r"\.(\d+)$")[0].dropna().str.len()
    if decimals.empty:
        return 0
    return int(np.clip(decimals.mode().iloc[0], 0, 6))
