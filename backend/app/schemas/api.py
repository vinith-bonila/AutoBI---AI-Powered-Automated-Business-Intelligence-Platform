"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .analysis import AnalysisResult
from .dashboard import DashboardSpecification
from .enums import FilterOperator, JobStatus
from .profile import DatasetProfile
from .quality import DataQualityReport


class PipelineStep(BaseModel):
    key: str
    label: str
    status: JobStatus = JobStatus.PENDING
    detail: str | None = None
    duration_ms: int | None = None


class JobState(BaseModel):
    dataset_id: str
    filename: str
    status: JobStatus = JobStatus.PENDING
    steps: list[PipelineStep] = Field(default_factory=list)
    progress: float = 0.0
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETE, JobStatus.FAILED)


class UploadResponse(BaseModel):
    dataset_id: str
    filename: str
    status: JobStatus
    message: str


class DatasetSummary(BaseModel):
    dataset_id: str
    name: str
    filename: str
    n_rows: int
    n_columns: int
    domain: str | None = None
    created_at: datetime
    status: JobStatus


class FilterValue(BaseModel):
    column: str
    operator: FilterOperator
    value: Any

    @field_validator("column")
    @classmethod
    def _no_injection(cls, v: str) -> str:
        # Column names are re-checked against the profile in the query layer;
        # this is a cheap first gate.
        if not v or len(v) > 200:
            raise ValueError("invalid column name")
        return v


class ChartDataRequest(BaseModel):
    filters: list[FilterValue] = Field(default_factory=list)
    # Optional per-request time-grain override (day|week|month|quarter|year).
    # Lets the same stored chart be re-aggregated without mutating the spec.
    time_grain: str | None = None


class ChartExecuteRequest(BaseModel):
    """Run an ad-hoc chart spec — used by chart switching and Add Visualization.

    The spec is validated server-side against the dataset before execution, so
    a client cannot run a chart the deterministic rules would reject.
    """

    chart: dict[str, Any]
    filters: list[FilterValue] = Field(default_factory=list)


class ChartValidateResponse(BaseModel):
    ok: bool
    reason: str | None = None
    allowed_types: list[str] = Field(default_factory=list)


class ChartDataPoint(BaseModel):
    """Generic row: `x`, one or more measure keys, optional metadata."""

    model_config = {"extra": "allow"}


class ChartDataResponse(BaseModel):
    chart_id: str
    type: str
    x_key: str
    y_keys: list[str]
    data: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    empty_reason: str | None = None


class KPIRefreshResponse(BaseModel):
    kpis: list[dict[str, Any]]
    row_count: int


class DashboardResponse(BaseModel):
    dataset_id: str
    filename: str
    specification: DashboardSpecification
    profile: DatasetProfile
    quality: DataQualityReport
    analysis: AnalysisResult
    ai_enabled: bool
    created_at: datetime


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int


class FieldInfo(BaseModel):
    """A column, described for the customization UI."""

    name: str
    label: str
    inferred_type: str
    semantic_role: str
    is_measure: bool
    is_dimension: bool
    is_temporal: bool
    unique: int
    missing_pct: float
    suggested_aggregation: str


class FieldsResponse(BaseModel):
    fields: list[FieldInfo]
    measures: list[str]
    dimensions: list[str]
    temporal: list[str]
    primary_date_column: str | None = None
    primary_measure_column: str | None = None
    default_time_grain: str | None = None


class AskRequest(BaseModel):
    question: str
    filters: list[FilterValue] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def _bounded(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be empty")
        return v[:500]


class AskEvidence(BaseModel):
    label: str
    value: str
    detail: str | None = None


class AskChart(BaseModel):
    """An optional supporting chart returned with an answer."""

    chart: dict[str, Any]
    data: ChartDataResponse


class AskResponse(BaseModel):
    question: str
    answer: str
    interpretation: str
    evidence: list[AskEvidence] = Field(default_factory=list)
    table: list[dict[str, Any]] = Field(default_factory=list)
    table_columns: list[str] = Field(default_factory=list)
    chart: AskChart | None = None
    ai_used: bool = False
    warning: str | None = None


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
