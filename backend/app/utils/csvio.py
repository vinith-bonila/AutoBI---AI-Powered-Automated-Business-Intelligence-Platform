"""Safe CSV ingestion.

Uploaded files are untrusted. This module:
  * enforces extension and size limits before anything is parsed,
  * sniffs delimiter and encoding rather than trusting the client,
  * parses everything as `string` first so pandas never guesses a type we
    have not audited (type inference is the profiler's job, not the reader's),
  * caps the number of rows read.
"""

from __future__ import annotations

import csv
import io
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .logging import get_logger

log = get_logger(__name__)

_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
_DELIMITERS = [",", ";", "\t", "|"]
_NA_BASE_TOKENS = [
    "",
    "na",
    "n/a",
    "n.a.",
    "nan",
    "null",
    "none",
    "nil",
    "-",
    "--",
    "?",
    "missing",
    "unknown",
    "#n/a",
    "#value!",
    "#ref!",
    "#div/0!",
]
# pandas matches `na_values` literally, so every casing a spreadsheet might
# emit has to be listed explicitly.
_NA_TOKENS = sorted(
    {
        variant
        for token in _NA_BASE_TOKENS
        for variant in (token, token.upper(), token.title(), token.capitalize())
    }
)


class CSVParseError(ValueError):
    """Raised when a file cannot be parsed as tabular CSV."""


@dataclass
class ParsedCSV:
    frame: pd.DataFrame
    delimiter: str
    encoding: str
    original_rows: int
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _detect_encoding(raw: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            raw[:200_000].decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))
        if dialect.delimiter in _DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass
    # Fall back to whichever candidate yields the most consistent column count.
    lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
    if not lines:
        raise CSVParseError("File appears to be empty.")
    best, best_score = ",", -1.0
    for delim in _DELIMITERS:
        counts = [len(next(csv.reader([ln], delimiter=delim))) for ln in lines]
        if not counts or max(counts) < 2:
            continue
        consistency = counts.count(counts[0]) / len(counts)
        score = counts[0] * consistency
        if score > best_score:
            best, best_score = delim, score
    return best


def _dedupe_columns(columns: list[str]) -> tuple[list[str], list[str]]:
    """Ensure unique, non-empty, trimmed column names."""
    seen: dict[str, int] = {}
    out: list[str] = []
    notes: list[str] = []
    for idx, raw in enumerate(columns):
        name = str(raw).strip().replace("\n", " ").replace("\r", " ")
        name = " ".join(name.split())
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{idx + 1}"
            notes.append(f"Unnamed column renamed to `{name}`.")
        if name in seen:
            seen[name] += 1
            new = f"{name}_{seen[name]}"
            notes.append(f"Duplicate column `{name}` renamed to `{new}`.")
            name = new
        else:
            seen[name] = 0
        out.append(name)
    return out, notes


def validate_upload(filename: str, size: int, *, max_bytes: int, allowed: tuple[str, ...]) -> None:
    """Gate an upload before any bytes are written to disk."""
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise CSVParseError(
            f"Unsupported file type `{suffix or 'unknown'}`. "
            f"Allowed: {', '.join(allowed)}."
        )
    if size <= 0:
        raise CSVParseError("Uploaded file is empty.")
    if size > max_bytes:
        raise CSVParseError(
            f"File is {size / 1_048_576:.1f} MB; the limit is "
            f"{max_bytes / 1_048_576:.0f} MB."
        )


def read_csv(path: Path, *, max_rows: int = 1_000_000) -> ParsedCSV:
    """Read a CSV/TSV file into an all-string DataFrame."""
    raw = path.read_bytes()
    if not raw.strip():
        raise CSVParseError("Uploaded file is empty.")

    encoding = _detect_encoding(raw)
    sample = raw[:64_000].decode(encoding, errors="replace")
    delimiter = _detect_delimiter(sample)
    parse_warnings: list[str] = []

    caught: list[warnings.WarningMessage] = []
    try:
        # pandas reports structural problems (ragged rows, header mismatch) as
        # warnings. Those matter to the user, so they are captured and surfaced
        # in the quality report rather than written to the server log.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame = pd.read_csv(
                io.BytesIO(raw),
                sep=delimiter,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                na_values=_NA_TOKENS,
                skip_blank_lines=True,
                on_bad_lines="skip",
                engine="python",
                # Without this, a row carrying more fields than the header makes
                # pandas silently promote the leading columns to an index, which
                # drops every correctly-shaped row in the file.
                index_col=False,
                nrows=max_rows + 1,
            )
    except pd.errors.EmptyDataError as exc:
        raise CSVParseError("No parsable rows found in the file.") from exc
    except pd.errors.ParserError as exc:
        raise CSVParseError(f"Could not parse the file as CSV: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise CSVParseError(f"Failed to read file: {exc}") from exc

    if frame.empty:
        raise CSVParseError("The file contains a header but no data rows.")
    if frame.shape[1] < 1:
        raise CSVParseError("No columns were detected.")

    for message in caught:
        text = str(message.message)
        if "Length of header" in text or "does not match" in text:
            parse_warnings.append(
                "Some rows carried more fields than the header and were trimmed "
                "to match it."
            )
        elif "Skipping line" in text:
            parse_warnings.append("Some malformed lines were skipped.")

    truncated = len(frame) > max_rows
    if truncated:
        frame = frame.head(max_rows)
        parse_warnings.append(
            f"Only the first {max_rows:,} rows were analyzed (file is larger)."
        )

    columns, notes = _dedupe_columns(list(frame.columns))
    frame.columns = columns
    parse_warnings.extend(notes)

    # Drop columns and rows that are entirely empty.
    empty_cols = [c for c in frame.columns if frame[c].isna().all()]
    if empty_cols and len(empty_cols) < frame.shape[1]:
        parse_warnings.append(
            f"{len(empty_cols)} fully-empty column(s) detected: "
            f"{', '.join(empty_cols[:5])}."
        )
    before = len(frame)
    frame = frame.dropna(how="all").reset_index(drop=True)
    if len(frame) < before:
        parse_warnings.append(f"Removed {before - len(frame):,} fully-empty row(s).")

    if frame.empty:
        raise CSVParseError("Every row in the file was empty.")

    log.info(
        "Parsed %s: %d rows x %d cols (delim=%r encoding=%s)",
        path.name,
        len(frame),
        frame.shape[1],
        delimiter,
        encoding,
    )
    return ParsedCSV(
        frame=frame,
        delimiter=delimiter,
        encoding=encoding,
        original_rows=len(frame),
        truncated=truncated,
        warnings=sorted(set(parse_warnings), key=parse_warnings.index),
    )
