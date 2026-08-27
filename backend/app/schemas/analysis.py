"""Results of the deterministic EDA engine.

These objects are the *only* factual source the LLM is allowed to narrate from.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CorrelationPair(BaseModel):
    x: str
    y: str
    coefficient: float
    strength: str  # weak | moderate | strong
    direction: str  # positive | negative
    p_value: float | None = None
    n: int = 0


class TrendPoint(BaseModel):
    period: str
    value: float


class TrendAnalysis(BaseModel):
    measure: str
    date_column: str
    grain: str
    points: list[TrendPoint] = Field(default_factory=list)
    first_value: float | None = None
    last_value: float | None = None
    change_pct: float | None = None
    direction: str = "flat"
    slope: float | None = None
    r_squared: float | None = None
    best_period: TrendPoint | None = None
    worst_period: TrendPoint | None = None
    period_over_period_pct: float | None = None
    volatility_pct: float | None = None
    partial_period_excluded: str | None = None


class SegmentRow(BaseModel):
    label: str
    value: float
    share_pct: float
    count: int = 0


class SegmentAnalysis(BaseModel):
    dimension: str
    measure: str
    aggregation: str
    top: list[SegmentRow] = Field(default_factory=list)
    bottom: list[SegmentRow] = Field(default_factory=list)
    n_categories: int = 0
    concentration_pct: float | None = None  # share of top 3
    gini: float | None = None
    has_negative_values: bool = False
    share_basis: str = "total"  # total | absolute_total


class OutlierReport(BaseModel):
    column: str
    method: str = "iqr"
    count: int = 0
    pct: float = 0.0
    lower_bound: float | None = None
    upper_bound: float | None = None
    extreme_values: list[float] = Field(default_factory=list)


class AnomalyReport(BaseModel):
    """A time-series point that deviates strongly from its local trend."""

    measure: str
    period: str
    value: float
    expected: float
    deviation_pct: float
    z_score: float


class DistributionSummary(BaseModel):
    column: str
    shape: str  # normal-ish | right-skewed | left-skewed | bimodal-ish | uniform-ish
    skew: float | None = None
    kurtosis: float | None = None
    bins: list[float] = Field(default_factory=list)
    counts: list[int] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    dataset_id: str
    row_count: int
    correlations: list[CorrelationPair] = Field(default_factory=list)
    trends: list[TrendAnalysis] = Field(default_factory=list)
    segments: list[SegmentAnalysis] = Field(default_factory=list)
    outliers: list[OutlierReport] = Field(default_factory=list)
    anomalies: list[AnomalyReport] = Field(default_factory=list)
    distributions: list[DistributionSummary] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def evidence_bundle(self) -> dict:
        """Compact, factual summary handed to the LLM for insight writing."""
        return {
            "trends": [
                {
                    "measure": t.measure,
                    "grain": t.grain,
                    "from": t.first_value,
                    "to": t.last_value,
                    "change_pct": t.change_pct,
                    "direction": t.direction,
                    "best_period": t.best_period.model_dump() if t.best_period else None,
                    "worst_period": (
                        t.worst_period.model_dump() if t.worst_period else None
                    ),
                    "latest_period_change_pct": t.period_over_period_pct,
                    "volatility_pct": t.volatility_pct,
                    "partial_period_excluded": t.partial_period_excluded,
                }
                for t in self.trends
            ],
            "segments": [
                {
                    "dimension": s.dimension,
                    "measure": s.measure,
                    "top": [r.model_dump() for r in s.top[:5]],
                    "bottom": [r.model_dump() for r in s.bottom[:3]],
                    "n_categories": s.n_categories,
                    "top3_share_pct": s.concentration_pct,
                }
                for s in self.segments
            ],
            "correlations": [
                c.model_dump(exclude={"p_value"}) for c in self.correlations[:8]
            ],
            "outliers": [
                {"column": o.column, "count": o.count, "pct": o.pct}
                for o in self.outliers
                if o.count
            ],
            "anomalies": [a.model_dump() for a in self.anomalies[:6]],
            "distributions": [
                {"column": d.column, "shape": d.shape, "skew": d.skew}
                for d in self.distributions
            ],
        }
