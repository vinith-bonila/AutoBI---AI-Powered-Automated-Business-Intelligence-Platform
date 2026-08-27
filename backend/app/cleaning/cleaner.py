"""Automated, auditable data cleaning.

Design rules:
  1. Never silently destroy data. Every mutation appends a `CleaningAction`
     with the affected row count and a human-readable reason.
  2. Never invent numbers. Missing numeric values stay missing — aggregations
     skip them — because imputing a mean would corrupt every KPI downstream.
  3. Only commit a type conversion the profiler already validated on the real
     values, above a confidence threshold.
"""

from __future__ import annotations

import pandas as pd

from ..config import Settings
from ..schemas.enums import CleaningActionType, InferredType, SemanticRole
from ..schemas.profile import DatasetProfile
from ..schemas.quality import CleaningAction, DataQualityReport, MissingSummary
from ..utils import coercion
from ..utils.logging import get_logger

log = get_logger(__name__)

# A conversion must succeed on this share of non-null values to be committed.
CONVERSION_THRESHOLD = 0.8
# Columns emptier than this are dropped (and reported).
DROP_MISSING_THRESHOLD = 0.95
# Categorical columns below this missing rate get an explicit "Unknown" label.
CATEGORICAL_FILL_THRESHOLD = 0.4
UNKNOWN_LABEL = "Unknown"
# Above this share of duplicate rows, de-duplication is treated as unsafe
# unless the dataset has an identifier column to justify it.
DUPLICATE_SAFETY_THRESHOLD = 0.30


class CleaningResult:
    def __init__(self, frame: pd.DataFrame, report: DataQualityReport):
        self.frame = frame
        self.report = report


def _count_changed(before: pd.Series, after: pd.Series) -> int:
    """Rows whose textual representation changed."""
    b = before.astype("string").fillna("<NA>")
    a = after.astype("string").fillna("<NA>")
    return int((b != a).sum())


def clean_dataset(
    frame: pd.DataFrame,
    profile: DatasetProfile,
    *,
    settings: Settings,
    extra_warnings: list[str] | None = None,
) -> CleaningResult:
    """Apply the cleaning pipeline and produce a full audit report."""
    df = frame.copy()
    actions: list[CleaningAction] = []
    warnings: list[str] = list(extra_warnings or [])
    dropped: list[str] = []

    rows_before = len(df)
    cols_before = df.shape[1]
    missing_before = int(df.isna().sum().sum())

    # -- 1. whitespace + empty-string normalisation ------------------------
    for col in df.columns:
        if df[col].dtype != object and str(df[col].dtype) != "string":
            continue
        original = df[col]
        stripped = original.astype("string").str.strip()
        # Collapse internal runs of whitespace so "North  East" == "North East".
        stripped = stripped.str.replace(r"\s+", " ", regex=True)
        blanks = stripped.isin(["", "-", "--", "N/A", "n/a", "NULL", "null", "None"])
        normalized = stripped.mask(blanks)

        trimmed_rows = int((original.astype("string") != stripped).fillna(False).sum())
        blank_rows = int(blanks.fillna(False).sum())
        df[col] = normalized

        if trimmed_rows:
            actions.append(
                CleaningAction(
                    action=CleaningActionType.TRIM_WHITESPACE,
                    column=col,
                    rows_affected=trimmed_rows,
                    reason="Leading, trailing or repeated whitespace removed.",
                )
            )
        if blank_rows:
            actions.append(
                CleaningAction(
                    action=CleaningActionType.NORMALIZE_EMPTY,
                    column=col,
                    rows_affected=blank_rows,
                    reason="Placeholder values treated as missing.",
                    detail="Empty strings and tokens like `-`, `N/A`, `null`.",
                )
            )

    # -- 2. drop columns that carry no information -------------------------
    for col_profile in profile.columns:
        col = col_profile.name
        if col not in df.columns:
            continue
        missing_ratio = df[col].isna().mean()
        if col_profile.inferred_type == InferredType.EMPTY or missing_ratio >= DROP_MISSING_THRESHOLD:
            df = df.drop(columns=[col])
            dropped.append(col)
            actions.append(
                CleaningAction(
                    action=CleaningActionType.DROP_COLUMN,
                    column=col,
                    rows_affected=rows_before,
                    reason=f"Column is {missing_ratio:.0%} empty and cannot support analysis.",
                )
            )
        elif col_profile.is_constant:
            warnings.append(
                f"`{col}` holds a single repeated value and was excluded from charts."
            )

    # -- 3. commit type conversions ---------------------------------------
    for col_profile in profile.columns:
        col = col_profile.name
        if col not in df.columns:
            continue
        series = df[col]

        if col_profile.inferred_type == InferredType.DATETIME:
            result = coercion.try_datetime(series, col)
            if result.success_ratio >= CONVERSION_THRESHOLD:
                unparsed = int(
                    (series.notna() & result.series.isna()).sum()
                )
                df[col] = result.series
                actions.append(
                    CleaningAction(
                        action=CleaningActionType.PARSE_DATETIME,
                        column=col,
                        rows_affected=int(result.series.notna().sum()),
                        reason="Text values recognised as dates and parsed to timestamps.",
                        detail=(
                            f"{unparsed:,} value(s) could not be parsed and are missing."
                            if unparsed
                            else (result.notes[0] if result.notes else None)
                        ),
                    )
                )

        elif col_profile.inferred_type == InferredType.NUMERIC:
            result = coercion.try_numeric(series)
            if result.success_ratio >= CONVERSION_THRESHOLD:
                unparsed = int((series.notna() & result.series.isna()).sum())
                had_symbols = bool(result.notes)
                df[col] = result.series
                if had_symbols:
                    action_type = (
                        CleaningActionType.STRIP_CURRENCY
                        if result.metadata.get("currency")
                        else CleaningActionType.PARSE_PERCENT
                        if result.metadata.get("percent")
                        else CleaningActionType.PARSE_NUMERIC
                    )
                else:
                    action_type = CleaningActionType.PARSE_NUMERIC
                actions.append(
                    CleaningAction(
                        action=action_type,
                        column=col,
                        rows_affected=int(result.series.notna().sum()),
                        reason="Text values converted to numbers for aggregation.",
                        detail=(
                            "; ".join(result.notes) if result.notes else None
                        )
                        + (
                            f" ({unparsed:,} unparsable value(s) set to missing)"
                            if unparsed
                            else ""
                        )
                        if (result.notes or unparsed)
                        else None,
                    )
                )

        elif col_profile.inferred_type == InferredType.BOOLEAN:
            result = coercion.try_boolean(series)
            if result.success_ratio >= 0.95:
                df[col] = result.series
                actions.append(
                    CleaningAction(
                        action=CleaningActionType.CAST_BOOLEAN,
                        column=col,
                        rows_affected=int(result.series.notna().sum()),
                        reason="Two-state values normalised to true/false.",
                        detail=f"Recognised tokens: {result.metadata.get('tokens')}",
                    )
                )

    # -- 4. unify categorical spelling variants ----------------------------
    for col_profile in profile.columns:
        col = col_profile.name
        if col not in df.columns or col_profile.inferred_type != InferredType.CATEGORICAL:
            continue
        series = df[col].astype("string")
        keys = series.str.lower().str.strip()
        # Only act when case/whitespace variants actually collapse the space.
        if keys.nunique(dropna=True) >= series.nunique(dropna=True):
            continue
        canonical = (
            pd.DataFrame({"key": keys, "value": series})
            .dropna()
            .groupby(["key", "value"])
            .size()
            .reset_index(name="n")
            .sort_values(["key", "n"], ascending=[True, False])
            .drop_duplicates("key")
            .set_index("key")["value"]
        )
        mapped = keys.map(canonical)
        changed = _count_changed(series, mapped)
        if changed:
            df[col] = mapped
            actions.append(
                CleaningAction(
                    action=CleaningActionType.NORMALIZE_CATEGORY,
                    column=col,
                    rows_affected=changed,
                    reason="Category labels differing only by case or spacing were merged.",
                    detail=f"{series.nunique()} → {mapped.nunique()} distinct labels.",
                )
            )

    # -- 5. exact duplicate rows -------------------------------------------
    # Removing exact duplicates is only safe when a repeated row really is the
    # same record. A narrow table of categorical columns (a survey, an event
    # log) legitimately repeats combinations, and de-duplicating it would
    # silently delete most of the dataset — so we warn instead of cutting.
    duplicate_candidates = int(df.duplicated().sum())
    duplicates = 0
    if duplicate_candidates:
        duplicate_share = duplicate_candidates / rows_before if rows_before else 0.0
        has_identifier = any(
            c.semantic_role == SemanticRole.IDENTIFIER and c.name in df.columns
            for c in profile.columns
        )
        if duplicate_share > DUPLICATE_SAFETY_THRESHOLD and not has_identifier:
            warnings.append(
                f"{duplicate_candidates:,} repeated rows ({duplicate_share:.0%} of the "
                "dataset) were kept: with no identifier column they are likely genuine "
                "repeated observations rather than duplicated records."
            )
        else:
            duplicates = duplicate_candidates
            df = df.drop_duplicates().reset_index(drop=True)
            actions.append(
                CleaningAction(
                    action=CleaningActionType.DROP_DUPLICATES,
                    rows_affected=duplicates,
                    reason="Fully identical rows removed to avoid double counting.",
                    detail=(
                        f"{duplicates:,} of {rows_before:,} rows were exact duplicates."
                    ),
                )
            )

    # -- 6. missing-value strategy ----------------------------------------
    missing_summary: list[MissingSummary] = []
    for col in df.columns:
        missing = int(df[col].isna().sum())
        if not missing:
            continue
        pct = missing / len(df) * 100 if len(df) else 0.0
        col_profile = profile.column(col)
        inferred = col_profile.inferred_type if col_profile else InferredType.TEXT

        if inferred == InferredType.CATEGORICAL and pct <= CATEGORICAL_FILL_THRESHOLD * 100:
            df[col] = df[col].astype("string").fillna(UNKNOWN_LABEL)
            strategy = f"Filled with `{UNKNOWN_LABEL}` so the category stays visible."
            actions.append(
                CleaningAction(
                    action=CleaningActionType.FILL_MISSING,
                    column=col,
                    rows_affected=missing,
                    reason=f"Missing category labels replaced with `{UNKNOWN_LABEL}`.",
                    detail="Rows are kept so totals still reconcile.",
                )
            )
        elif inferred == InferredType.NUMERIC:
            strategy = "Left missing — excluded from aggregations, never imputed."
        elif inferred == InferredType.DATETIME:
            strategy = "Left missing — excluded from time-series analysis."
        else:
            strategy = "Left missing."

        missing_summary.append(
            MissingSummary(
                column=col,
                missing=missing,
                missing_pct=round(pct, 2),
                strategy=strategy,
            )
        )

    missing_summary.sort(key=lambda m: -m.missing_pct)

    # -- 7. scores ---------------------------------------------------------
    cells = max(len(df) * max(df.shape[1], 1), 1)
    missing_after = int(df.isna().sum().sum())
    completeness = max(0.0, 100.0 - (missing_after / cells * 100))
    uniqueness = 100.0 if rows_before == 0 else max(
        0.0, 100.0 - (duplicates / rows_before * 100)
    )
    typed_columns = sum(
        1
        for c in profile.columns
        if c.inferred_type in (InferredType.NUMERIC, InferredType.DATETIME, InferredType.BOOLEAN, InferredType.CATEGORICAL)
    )
    consistency = (typed_columns / cols_before * 100) if cols_before else 100.0
    quality = round(0.5 * completeness + 0.3 * uniqueness + 0.2 * consistency, 1)

    if len(df) == 0:
        warnings.append("No rows remained after cleaning.")
    if not [c for c in profile.columns if c.semantic_role in (SemanticRole.MEASURE, SemanticRole.CURRENCY, SemanticRole.QUANTITY)]:
        warnings.append(
            "No numeric measure was detected — the dashboard will focus on counts and distributions."
        )

    report = DataQualityReport(
        dataset_id=profile.dataset_id,
        rows_before=rows_before,
        rows_after=len(df),
        columns_before=cols_before,
        columns_after=df.shape[1],
        duplicates_removed=duplicates,
        total_missing_before=missing_before,
        total_missing_after=missing_after,
        actions=actions,
        missing_summary=missing_summary,
        dropped_columns=dropped,
        warnings=warnings,
        completeness_score=round(completeness, 1),
        uniqueness_score=round(uniqueness, 1),
        consistency_score=round(consistency, 1),
        quality_score=quality,
    )

    log.info(
        "Cleaned %s: %d->%d rows, %d->%d cols, %d actions, quality=%.1f",
        profile.name, rows_before, len(df), cols_before, df.shape[1],
        len(actions), quality,
    )
    return CleaningResult(df.reset_index(drop=True), report)
