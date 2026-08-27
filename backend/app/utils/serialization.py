"""Convert numpy/pandas scalars into JSON-safe Python primitives."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_native(value: Any) -> Any:
    """Best-effort conversion of any pandas/numpy value to a JSON-safe type."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (np.str_, str)):
        return str(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta,)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.ndarray, list, tuple)):
        return [to_native(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_native(v) for k, v in value.items()}
    return str(value)


def safe_float(value: Any) -> float | None:
    """Return a finite float or None."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe dicts."""
    return [
        {str(k): to_native(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]
