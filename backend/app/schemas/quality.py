"""Data quality / cleaning report contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import CleaningActionType


class CleaningAction(BaseModel):
    action: CleaningActionType
    column: str | None = None
    rows_affected: int = 0
    reason: str
    detail: str | None = None

    @property
    def label(self) -> str:
        target = f" `{self.column}`" if self.column else ""
        return f"{self.action.value}{target}"


class MissingSummary(BaseModel):
    column: str
    missing: int
    missing_pct: float
    strategy: str


class DataQualityReport(BaseModel):
    dataset_id: str
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    duplicates_removed: int = 0
    total_missing_before: int = 0
    total_missing_after: int = 0

    actions: list[CleaningAction] = Field(default_factory=list)
    missing_summary: list[MissingSummary] = Field(default_factory=list)
    dropped_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    completeness_score: float = 100.0
    uniqueness_score: float = 100.0
    consistency_score: float = 100.0
    quality_score: float = 100.0

    @property
    def rows_removed(self) -> int:
        return self.rows_before - self.rows_after
