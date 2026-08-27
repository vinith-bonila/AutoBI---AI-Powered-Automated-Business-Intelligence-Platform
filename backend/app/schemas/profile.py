"""Dataset profiling contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import InferredType, SemanticRole


class ValueCount(BaseModel):
    value: str
    count: int
    pct: float


class NumericStats(BaseModel):
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    p25: float | None = None
    p75: float | None = None
    p05: float | None = None
    p95: float | None = None
    skew: float | None = None
    sum: float | None = None
    zero_pct: float = 0.0
    negative_pct: float = 0.0
    outlier_count: int = 0


class DatetimeStats(BaseModel):
    min: str | None = None
    max: str | None = None
    range_days: int | None = None
    suggested_grain: str | None = None
    distinct_days: int | None = None


class ColumnProfile(BaseModel):
    name: str
    original_dtype: str
    inferred_type: InferredType
    semantic_role: SemanticRole
    role_confidence: float = Field(0.5, ge=0.0, le=1.0)
    role_evidence: list[str] = Field(default_factory=list)

    count: int
    missing: int
    missing_pct: float
    unique: int
    cardinality_ratio: float
    is_constant: bool = False
    is_unique_key: bool = False

    numeric: NumericStats | None = None
    datetime: DatetimeStats | None = None
    top_values: list[ValueCount] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)

    def is_measure(self) -> bool:
        from .enums import MEASURE_ROLES

        return self.semantic_role in MEASURE_ROLES

    def is_dimension(self) -> bool:
        from .enums import DIMENSION_ROLES

        return self.semantic_role in DIMENSION_ROLES


class DatasetProfile(BaseModel):
    dataset_id: str
    name: str
    n_rows: int
    n_columns: int
    n_duplicate_rows: int
    memory_bytes: int
    columns: list[ColumnProfile]

    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    datetime_columns: list[str] = Field(default_factory=list)
    boolean_columns: list[str] = Field(default_factory=list)
    text_columns: list[str] = Field(default_factory=list)
    identifier_columns: list[str] = Field(default_factory=list)
    measure_columns: list[str] = Field(default_factory=list)
    dimension_columns: list[str] = Field(default_factory=list)

    primary_date_column: str | None = None
    primary_measure_column: str | None = None
    domain_guess: str | None = None
    domain_signals: list[str] = Field(default_factory=list)

    def column(self, name: str) -> ColumnProfile | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def compact(self) -> dict[str, Any]:
        """A token-efficient view of the profile for LLM prompts."""
        return {
            "rows": self.n_rows,
            "columns": self.n_columns,
            "domain_signals": self.domain_signals,
            "primary_date_column": self.primary_date_column,
            "fields": [
                {
                    "name": c.name,
                    "type": c.inferred_type.value,
                    "role": c.semantic_role.value,
                    "missing_pct": round(c.missing_pct, 2),
                    "unique": c.unique,
                    **(
                        {
                            "min": _r(c.numeric.min),
                            "max": _r(c.numeric.max),
                            "mean": _r(c.numeric.mean),
                            "sum": _r(c.numeric.sum),
                        }
                        if c.numeric
                        else {}
                    ),
                    **(
                        {"from": c.datetime.min, "to": c.datetime.max}
                        if c.datetime
                        else {}
                    ),
                    **(
                        {"top": [v.value for v in c.top_values[:6]]}
                        if c.top_values
                        else {}
                    ),
                }
                for c in self.columns
            ],
        }


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)
