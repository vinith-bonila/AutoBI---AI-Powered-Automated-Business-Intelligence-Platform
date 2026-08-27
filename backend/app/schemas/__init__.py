"""Pydantic contracts for the AutoBI pipeline."""

from .analysis import AnalysisResult
from .dashboard import (
    ChartSpecification,
    DashboardSpecification,
    FilterSpecification,
    Insight,
    KPI,
)
from .profile import ColumnProfile, DatasetProfile
from .quality import DataQualityReport

__all__ = [
    "AnalysisResult",
    "ChartSpecification",
    "ColumnProfile",
    "DashboardSpecification",
    "DataQualityReport",
    "DatasetProfile",
    "FilterSpecification",
    "Insight",
    "KPI",
]
