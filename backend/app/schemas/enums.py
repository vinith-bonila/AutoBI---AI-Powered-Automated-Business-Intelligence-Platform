"""Controlled vocabularies shared across the analysis pipeline.

Every enum here is part of the public contract: the LLM is asked to choose from
these values, the validator rejects anything outside them, and the frontend
switches on them when rendering.
"""

from __future__ import annotations

from enum import Enum


class InferredType(str, Enum):
    """Physical/statistical type of a column after type detection."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    TEXT = "text"
    EMPTY = "empty"


class SemanticRole(str, Enum):
    """What a column *means* in business terms."""

    MEASURE = "measure"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    QUANTITY = "quantity"
    RATIO = "ratio"
    DIMENSION = "dimension"
    TIME = "time"
    GEO = "geo"
    IDENTIFIER = "identifier"
    DEMOGRAPHIC = "demographic"
    FLAG = "flag"
    TEXT = "text"
    UNKNOWN = "unknown"


MEASURE_ROLES = {
    SemanticRole.MEASURE,
    SemanticRole.CURRENCY,
    SemanticRole.QUANTITY,
    SemanticRole.PERCENTAGE,
    SemanticRole.RATIO,
}

DIMENSION_ROLES = {
    SemanticRole.DIMENSION,
    SemanticRole.GEO,
    SemanticRole.FLAG,
    SemanticRole.DEMOGRAPHIC,
}


class ChartType(str, Enum):
    LINE = "line"
    BAR = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    HEATMAP = "heatmap"
    TABLE = "table"


class Aggregation(str, Enum):
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    MEDIAN = "median"
    NONE = "none"


class TimeGrain(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class ValueFormat(str, Enum):
    CURRENCY = "currency"
    NUMBER = "number"
    PERCENT = "percent"
    COUNT = "count"
    DECIMAL = "decimal"
    DURATION_DAYS = "duration_days"


class FilterKind(str, Enum):
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    DATE_RANGE = "date_range"
    NUMERIC_RANGE = "numeric_range"


class FilterOperator(str, Enum):
    EQUALS = "eq"
    IN = "in"
    BETWEEN = "between"
    GTE = "gte"
    LTE = "lte"


class InsightCategory(str, Enum):
    TREND = "trend"
    ANOMALY = "anomaly"
    SEGMENT = "segment"
    CORRELATION = "correlation"
    DISTRIBUTION = "distribution"
    QUALITY = "quality"
    RECOMMENDATION = "recommendation"
    SUMMARY = "summary"


class InsightSeverity(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    WARNING = "warning"
    CRITICAL = "critical"


class CleaningActionType(str, Enum):
    PARSE_DATETIME = "parse_datetime"
    PARSE_NUMERIC = "parse_numeric"
    STRIP_CURRENCY = "strip_currency"
    PARSE_PERCENT = "parse_percent"
    TRIM_WHITESPACE = "trim_whitespace"
    NORMALIZE_EMPTY = "normalize_empty"
    DROP_DUPLICATES = "drop_duplicates"
    FILL_MISSING = "fill_missing"
    DROP_COLUMN = "drop_column"
    CAST_BOOLEAN = "cast_boolean"
    NORMALIZE_CATEGORY = "normalize_category"
    FLAG_OUTLIERS = "flag_outliers"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class GenerationSource(str, Enum):
    """Where a piece of the dashboard spec came from."""

    DETERMINISTIC = "deterministic"
    AI = "ai"
    HYBRID = "hybrid"
