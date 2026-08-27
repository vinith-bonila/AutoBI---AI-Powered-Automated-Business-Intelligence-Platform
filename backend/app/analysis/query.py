"""Controlled analytical query layer, backed by DuckDB.

Security model
--------------
The LLM never writes SQL. It selects a chart *type* and column *names*, and
this module compiles those into SQL itself:

  * every identifier is checked against the real column list of the loaded
    dataset and then quoted — an unknown name raises rather than reaching SQL;
  * every literal is bound as a parameter, never interpolated;
  * aggregations come from a fixed enum, not from text;
  * result sets are capped.

That means an attacker-controlled column name in a CSV, or a hallucinated
column from the model, can only ever produce a rejected query.
"""

from __future__ import annotations

import threading
from typing import Any, Sequence

import duckdb
import pandas as pd

from ..schemas.api import FilterValue
from ..schemas.enums import Aggregation, FilterOperator, TimeGrain
from ..utils.logging import get_logger

log = get_logger(__name__)

_AGG_SQL: dict[Aggregation, str] = {
    Aggregation.SUM: "SUM({col})",
    Aggregation.AVG: "AVG({col})",
    Aggregation.MIN: "MIN({col})",
    Aggregation.MAX: "MAX({col})",
    Aggregation.COUNT: "COUNT({col})",
    Aggregation.COUNT_DISTINCT: "COUNT(DISTINCT {col})",
    Aggregation.MEDIAN: "MEDIAN({col})",
}

_GRAIN_SQL: dict[TimeGrain, str] = {
    TimeGrain.DAY: "day",
    TimeGrain.WEEK: "week",
    TimeGrain.MONTH: "month",
    TimeGrain.QUARTER: "quarter",
    TimeGrain.YEAR: "year",
}

MAX_RESULT_ROWS = 5000


class QueryError(ValueError):
    """Raised when a query references something the dataset does not contain."""


def quote_ident(name: str) -> str:
    """Quote an identifier for DuckDB, escaping embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


class DatasetQuery:
    """A read-only analytical session over one cleaned dataset."""

    def __init__(self, frame: pd.DataFrame, *, table_name: str = "data"):
        self._frame = frame
        self._table = table_name
        self._lock = threading.Lock()
        self._conn = duckdb.connect(database=":memory:")
        self._conn.register(table_name, frame)
        self.columns: list[str] = [str(c) for c in frame.columns]
        self._column_set = set(self.columns)
        self._dtypes = {str(c): str(frame[c].dtype) for c in frame.columns}

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "DatasetQuery":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- validation --------------------------------------------------------

    def ident(self, column: str) -> str:
        if column not in self._column_set:
            raise QueryError(f"Unknown column `{column}`.")
        return quote_ident(column)

    def is_temporal(self, column: str) -> bool:
        return "datetime" in self._dtypes.get(column, "")

    def is_numeric(self, column: str) -> bool:
        dtype = self._dtypes.get(column, "").lower()
        if "bool" in dtype:
            return False
        return any(t in dtype for t in ("int", "float", "decimal"))

    # -- filter compilation ------------------------------------------------

    def _compile_filters(
        self, filters: Sequence[FilterValue]
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        for f in filters:
            col = self.ident(f.column)  # raises on unknown column
            temporal = self.is_temporal(f.column)
            cast = "CAST(? AS TIMESTAMP)" if temporal else "?"

            if f.operator == FilterOperator.EQUALS:
                if f.value in (None, ""):
                    continue
                clauses.append(f"{col} = {cast}")
                params.append(f.value)

            elif f.operator == FilterOperator.IN:
                values = f.value if isinstance(f.value, (list, tuple)) else [f.value]
                values = [v for v in values if v not in (None, "")]
                if not values:
                    continue
                placeholders = ", ".join([cast] * len(values))
                # Compare as text so numeric-looking categories still match.
                left = col if temporal else f"CAST({col} AS VARCHAR)"
                clauses.append(f"{left} IN ({placeholders})")
                params.extend([v if temporal else str(v) for v in values])

            elif f.operator == FilterOperator.BETWEEN:
                if not isinstance(f.value, (list, tuple)) or len(f.value) != 2:
                    continue
                lo, hi = f.value
                if lo not in (None, ""):
                    clauses.append(f"{col} >= {cast}")
                    params.append(lo)
                if hi not in (None, ""):
                    clauses.append(f"{col} <= {cast}")
                    params.append(hi)

            elif f.operator == FilterOperator.GTE:
                if f.value in (None, ""):
                    continue
                clauses.append(f"{col} >= {cast}")
                params.append(f.value)

            elif f.operator == FilterOperator.LTE:
                if f.value in (None, ""):
                    continue
                clauses.append(f"{col} <= {cast}")
                params.append(f.value)

        return clauses, params

    def _where(
        self,
        filters: Sequence[FilterValue],
        *extra_clauses: str,
        extra_params: Sequence[Any] = (),
    ) -> tuple[str, list[Any]]:
        """Assemble a WHERE clause from user filters plus internal guards.

        Internal guards (NOT NULL, top-N membership) are appended after the
        user filters so their bound parameters stay in positional order.
        """
        clauses, params = self._compile_filters(filters)
        clauses = clauses + [c for c in extra_clauses if c]
        params = params + list(extra_params)
        sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return sql, params

    def _run(self, sql: str, params: list[Any]) -> pd.DataFrame:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetch_df()
            except duckdb.Error as exc:
                log.warning("Query failed: %s | sql=%s", exc, sql)
                raise QueryError(f"Query could not be executed: {exc}") from exc

    def _agg_expr(self, measure: str | None, aggregation: Aggregation) -> str:
        if aggregation == Aggregation.COUNT and not measure:
            return "COUNT(*)"
        if not measure:
            raise QueryError(
                f"Aggregation `{aggregation.value}` needs a measure column."
            )
        template = _AGG_SQL.get(aggregation)
        if template is None:
            raise QueryError(f"Unsupported aggregation `{aggregation.value}`.")
        return template.format(col=self.ident(measure))

    # -- public query builders --------------------------------------------

    def row_count(self, filters: Sequence[FilterValue] = ()) -> int:
        where, params = self._where(filters)
        df = self._run(f"SELECT COUNT(*) AS n FROM {self._table}{where}", params)
        return int(df.iloc[0]["n"]) if not df.empty else 0

    def scalar(
        self,
        measure: str | None,
        aggregation: Aggregation,
        filters: Sequence[FilterValue] = (),
    ) -> float | None:
        expr = self._agg_expr(measure, aggregation)
        where, params = self._where(filters)
        df = self._run(f"SELECT {expr} AS value FROM {self._table}{where}", params)
        if df.empty:
            return None
        value = df.iloc[0]["value"]
        return None if pd.isna(value) else float(value)

    def is_boolean(self, column: str) -> bool:
        return "bool" in self._dtypes.get(column, "").lower()

    def conditional_count(
        self,
        column: str,
        equals: Any,
        filters: Sequence[FilterValue] = (),
    ) -> int:
        """COUNT of rows where `column` equals a value — used by rate KPIs.

        Booleans are compared natively: DuckDB renders them as `true`/`false`,
        which would never match Python's `True`/`False` under a text cast.
        """
        col = self.ident(column)
        if self.is_boolean(column) and isinstance(equals, bool):
            clause = f"{col} IS {'TRUE' if equals else 'FALSE'}"
            where, params = self._where(filters, clause)
        else:
            where, params = self._where(
                filters, f"CAST({col} AS VARCHAR) = ?", extra_params=[str(equals)]
            )
        df = self._run(f"SELECT COUNT(*) AS n FROM {self._table}{where}", params)
        return int(df.iloc[0]["n"]) if not df.empty else 0

    def aggregate_by_dimension(
        self,
        dimension: str,
        measure: str | None,
        aggregation: Aggregation,
        *,
        filters: Sequence[FilterValue] = (),
        limit: int = 20,
        sort: str = "value_desc",
        include_count: bool = True,
    ) -> pd.DataFrame:
        """GROUP BY one dimension. Columns: label, value[, row_count]."""
        dim = self.ident(dimension)
        expr = self._agg_expr(measure, aggregation)
        where, params = self._where(filters, f"{dim} IS NOT NULL")

        count_select = ", COUNT(*) AS row_count" if include_count else ""
        order = {
            "value_desc": "value DESC NULLS LAST",
            "value_asc": "value ASC NULLS LAST",
            "x_asc": "label ASC",
            "x_desc": "label DESC",
        }.get(sort, "value DESC NULLS LAST")

        sql = (
            f"SELECT CAST({dim} AS VARCHAR) AS label, {expr} AS value{count_select} "
            f"FROM {self._table}{where} "
            f"GROUP BY 1 ORDER BY {order} LIMIT {min(int(limit), MAX_RESULT_ROWS)}"
        )
        return self._run(sql, params)

    def aggregate_by_dimension_series(
        self,
        dimension: str,
        series: str,
        measure: str | None,
        aggregation: Aggregation,
        *,
        filters: Sequence[FilterValue] = (),
        limit: int = 20,
        series_limit: int = 6,
    ) -> pd.DataFrame:
        """GROUP BY dimension x series, restricted to the top series values."""
        top_series = self.aggregate_by_dimension(
            series, measure, aggregation, filters=filters,
            limit=series_limit, include_count=False,
        )
        keep = [str(v) for v in top_series["label"].tolist()]
        if not keep:
            return pd.DataFrame(columns=["label", "series", "value"])

        dim, ser = self.ident(dimension), self.ident(series)
        expr = self._agg_expr(measure, aggregation)
        placeholders = ", ".join(["?"] * len(keep))
        where, params = self._where(
            filters,
            f"{dim} IS NOT NULL",
            f"CAST({ser} AS VARCHAR) IN ({placeholders})",
            extra_params=keep,
        )
        sql = (
            f"SELECT CAST({dim} AS VARCHAR) AS label, "
            f"CAST({ser} AS VARCHAR) AS series, {expr} AS value "
            f"FROM {self._table}{where} GROUP BY 1, 2 ORDER BY 1 "
            f"LIMIT {min(int(limit) * series_limit, MAX_RESULT_ROWS)}"
        )
        return self._run(sql, params)

    def time_series(
        self,
        date_column: str,
        measure: str | None,
        aggregation: Aggregation,
        grain: TimeGrain,
        *,
        filters: Sequence[FilterValue] = (),
        series: str | None = None,
        series_limit: int = 5,
    ) -> pd.DataFrame:
        """Aggregate a measure over time. Columns: period, value[, series]."""
        date_col = self.ident(date_column)
        if not self.is_temporal(date_column):
            raise QueryError(f"`{date_column}` is not a date column.")
        expr = self._agg_expr(measure, aggregation)
        trunc = _GRAIN_SQL.get(grain, "month")

        if series:
            top = self.aggregate_by_dimension(
                series, measure, aggregation, filters=filters,
                limit=series_limit, include_count=False,
            )
            keep = [str(v) for v in top["label"].tolist()]
            if not keep:
                return pd.DataFrame(columns=["period", "series", "value"])
            ser = self.ident(series)
            placeholders = ", ".join(["?"] * len(keep))
            where, params = self._where(
                filters,
                f"{date_col} IS NOT NULL",
                f"CAST({ser} AS VARCHAR) IN ({placeholders})",
                extra_params=keep,
            )
            sql = (
                f"SELECT DATE_TRUNC('{trunc}', {date_col}) AS period, "
                f"CAST({ser} AS VARCHAR) AS series, {expr} AS value "
                f"FROM {self._table}{where} "
                f"GROUP BY 1, 2 ORDER BY 1, 2 LIMIT {MAX_RESULT_ROWS}"
            )
            return self._run(sql, params)

        where, params = self._where(filters, f"{date_col} IS NOT NULL")
        sql = (
            f"SELECT DATE_TRUNC('{trunc}', {date_col}) AS period, {expr} AS value, "
            f"COUNT(*) AS row_count FROM {self._table}{where} "
            f"GROUP BY 1 ORDER BY 1 LIMIT {MAX_RESULT_ROWS}"
        )
        return self._run(sql, params)

    def scatter(
        self,
        x: str,
        y: str,
        *,
        filters: Sequence[FilterValue] = (),
        series: str | None = None,
        limit: int = 2000,
    ) -> pd.DataFrame:
        x_col, y_col = self.ident(x), self.ident(y)
        where, params = self._where(
            filters, f"{x_col} IS NOT NULL", f"{y_col} IS NOT NULL"
        )
        series_select = (
            f", CAST({self.ident(series)} AS VARCHAR) AS series" if series else ""
        )
        sql = (
            f"SELECT {x_col} AS x, {y_col} AS y{series_select} "
            f"FROM {self._table}{where} "
            f"USING SAMPLE {min(int(limit), MAX_RESULT_ROWS)} ROWS"
        )
        return self._run(sql, params)

    def histogram(
        self,
        column: str,
        *,
        bins: int = 20,
        filters: Sequence[FilterValue] = (),
    ) -> pd.DataFrame:
        """Equal-width binning. Columns: bin_start, bin_end, label, count."""
        col = self.ident(column)
        if not self.is_numeric(column):
            raise QueryError(f"`{column}` is not numeric and cannot be binned.")
        bins = max(3, min(int(bins), 100))

        bounds_where, bounds_params = self._where(filters)
        bounds = self._run(
            f"SELECT MIN({col}) AS lo, MAX({col}) AS hi, COUNT({col}) AS n "
            f"FROM {self._table}{bounds_where}",
            bounds_params,
        )
        if bounds.empty or pd.isna(bounds.iloc[0]["lo"]) or int(bounds.iloc[0]["n"]) == 0:
            return pd.DataFrame(columns=["bin_start", "bin_end", "label", "count"])

        lo = float(bounds.iloc[0]["lo"])
        hi = float(bounds.iloc[0]["hi"])
        total = int(bounds.iloc[0]["n"])
        if hi <= lo:
            return pd.DataFrame(
                [{"bin_start": lo, "bin_end": hi, "label": f"{lo:g}", "count": total}]
            )
        width = (hi - lo) / bins

        where, params = self._where(filters, f"{col} IS NOT NULL")
        sql = (
            f"SELECT LEAST(CAST(FLOOR(({col} - ?) / ?) AS INTEGER), ?) AS bin_index, "
            f"COUNT(*) AS count FROM {self._table}{where} GROUP BY 1 ORDER BY 1"
        )
        # The three placeholders for lo/width/bins sit in the SELECT list,
        # which precedes the WHERE clause, so they bind first.
        raw = self._run(sql, [lo, width, bins - 1] + params)
        if raw.empty:
            return pd.DataFrame(columns=["bin_start", "bin_end", "label", "count"])

        counts = {int(r.bin_index): int(r.count) for r in raw.itertuples()}
        rows = []
        for i in range(bins):
            start, end = lo + i * width, lo + (i + 1) * width
            rows.append(
                {
                    "bin_start": round(start, 6),
                    "bin_end": round(end, 6),
                    "label": f"{start:,.4g} - {end:,.4g}",
                    "count": counts.get(i, 0),
                }
            )
        return pd.DataFrame(rows)

    def correlation_matrix(
        self, columns: Sequence[str], *, filters: Sequence[FilterValue] = ()
    ) -> pd.DataFrame:
        """Pearson correlation between numeric columns, computed in DuckDB."""
        cols = [c for c in columns if self.is_numeric(c)]
        for c in cols:
            self.ident(c)
        if len(cols) < 2:
            return pd.DataFrame(columns=["x", "y", "value"])

        where, params = self._where(filters)
        selects = []
        for a in cols:
            for b in cols:
                selects.append(
                    f"CORR({self.ident(a)}, {self.ident(b)}) AS "
                    f"{quote_ident(f'{a}||{b}')}"
                )
        sql = f"SELECT {', '.join(selects)} FROM {self._table}{where}"
        wide = self._run(sql, params)
        if wide.empty:
            return pd.DataFrame(columns=["x", "y", "value"])

        rows = []
        for name, value in wide.iloc[0].items():
            a, b = str(name).split("||", 1)
            rows.append(
                {
                    "x": a,
                    "y": b,
                    "value": None if pd.isna(value) else round(float(value), 4),
                }
            )
        return pd.DataFrame(rows)

    def table(
        self,
        columns: Sequence[str],
        *,
        filters: Sequence[FilterValue] = (),
        limit: int = 200,
        order_by: str | None = None,
        descending: bool = True,
    ) -> pd.DataFrame:
        cols = [self.ident(c) for c in columns]
        if not cols:
            raise QueryError("A table needs at least one column.")
        where, params = self._where(filters)
        order = ""
        if order_by:
            direction = "DESC" if descending else "ASC"
            order = f" ORDER BY {self.ident(order_by)} {direction} NULLS LAST"
        sql = (
            f"SELECT {', '.join(cols)} FROM {self._table}{where}{order} "
            f"LIMIT {min(int(limit), MAX_RESULT_ROWS)}"
        )
        return self._run(sql, params)

    def distinct_values(self, column: str, *, limit: int = 100) -> list[str]:
        col = self.ident(column)
        sql = (
            f"SELECT CAST({col} AS VARCHAR) AS value, COUNT(*) AS n "
            f"FROM {self._table} WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY n DESC LIMIT {int(limit)}"
        )
        df = self._run(sql, [])
        return [str(v) for v in df["value"].tolist()]

    def column_range(self, column: str) -> tuple[Any, Any]:
        col = self.ident(column)
        df = self._run(
            f"SELECT MIN({col}) AS lo, MAX({col}) AS hi FROM {self._table}", []
        )
        if df.empty:
            return (None, None)
        lo, hi = df.iloc[0]["lo"], df.iloc[0]["hi"]
        return (None if pd.isna(lo) else lo, None if pd.isna(hi) else hi)
