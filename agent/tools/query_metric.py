"""query_metric: the only path to numbers for the agent and the app (governed MetricFlow metrics).

Public tool (AGENTS.md: ask before changing it). Arguments that MetricFlow would silently
reinterpret are refused with ToolArgumentError rather than answered with a wrong number:
time filters (use time_range), partial or inverted dates, ranges not aligned to a grouped time
grain (MetricFlow widens them to the grain), bare `metric_time`, filter values the data
does not contain, and ranges that reach a period with no data (both would return a 0 that
looks like a real count). Provenance carries the data's date range for coverage caveats.
"""

import csv
import difflib
import functools
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

from agent.errors import ToolArgumentError
from agent.tools.catalog import Catalog, load_catalog
from core.warehouse import Warehouse, run_cli

logger = logging.getLogger(__name__)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Provenance:
    metrics: list[str]
    group_by: list[str]
    filters: dict[str, str]
    time_range: tuple[str | None, str | None]
    data_range: tuple[str, str]  # first and last date_received in the warehouse
    columns: list[str]
    snapshot_date: str
    source_sha256: str


@dataclass(frozen=True)
class MetricResult:
    rows: list[dict[str, str | int | float | None]]
    provenance: Provenance


def _parse_date(value: str) -> date:
    if not ISO_DATE.fullmatch(value):
        raise ToolArgumentError(f"time_range dates must be YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ToolArgumentError(f"invalid date {value!r}: {e}") from e


def _period_start(d: date, grain: str) -> date:
    if grain == "week":
        return d - timedelta(days=d.weekday())
    if grain == "month":
        return d.replace(day=1)
    if grain == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    if grain == "year":
        return d.replace(month=1, day=1)
    return d


def _period_end(d: date, grain: str) -> date:
    try:
        if grain == "week":
            return _period_start(d, grain) + timedelta(days=6)
        if grain in ("month", "quarter", "year"):
            months = {"month": 1, "quarter": 3, "year": 12}[grain]
            start = _period_start(d, grain)
            y, m = divmod(start.month - 1 + months, 12)
            return start.replace(year=start.year + y, month=m + 1) - timedelta(days=1)
    except (OverflowError, ValueError) as e:  # e.g. 9999-12-31: the period ends past year 9999
        raise ToolArgumentError(f"date {d} is out of range for the {grain} grain: {e}") from e
    return d


def _is_str_list(value: object) -> bool:
    return isinstance(value, list | tuple) and all(isinstance(v, str) for v in value)


def _check_types(metrics: object, group_by: object, filters: object, time_range: object) -> None:
    """Tool arguments arrive as model-written JSON: wrong shapes are the model's mistake."""
    if not _is_str_list(metrics) or not metrics:
        raise ToolArgumentError(f"metrics must be a non-empty list of names, got {metrics!r}")
    assert isinstance(metrics, list | tuple)
    if len(set(metrics)) != len(metrics):
        raise ToolArgumentError(f"metrics has duplicates: {list(metrics)}")
    if group_by is not None and not _is_str_list(group_by):
        raise ToolArgumentError(f"group_by must be a list of names, got {group_by!r}")
    if filters is not None and not isinstance(filters, dict):
        raise ToolArgumentError(f"filters must be an object {{dimension: value}}, got {filters!r}")
    if time_range is not None and (
        not isinstance(time_range, list | tuple) or len(time_range) != 2
        or not all(t is None or isinstance(t, str) for t in time_range)
    ):  # fmt: skip
        raise ToolArgumentError(f"time_range must be [start, end] strings, got {time_range!r}")


def _validate(
    catalog: Catalog,
    metrics: list[str],
    group_by: list[str],
    filters: dict[str, str],
    start: str | None,
    end: str | None,
) -> str:
    """Check names and dates against the semantic layer; return the time grain in effect."""
    unknown = [m for m in metrics if m not in catalog.metrics]
    if unknown or not metrics:
        raise ToolArgumentError(f"unknown metrics {unknown}; available: {sorted(catalog.metrics)}")
    grains = [g for g in group_by if g in catalog.time_grains]
    for g in group_by:
        if g == "metric_time" or (g.startswith("metric_time") and g not in catalog.time_grains):
            raise ToolArgumentError(
                f"group_by {g!r}: give an explicit grain, e.g. metric_time__month"
            )
        if g not in catalog.time_grains and g not in catalog.dimensions:
            available = sorted(catalog.dimensions | catalog.time_grains)
            raise ToolArgumentError(f"unknown group_by {g!r}; available: {available}")
    if len(grains) > 1:
        raise ToolArgumentError(f"group by at most one time grain, got {grains}")
    for dim, value in filters.items():
        if dim.startswith("metric_time"):
            raise ToolArgumentError(f"filter {dim!r}: constrain time with time_range, not filters")
        if dim not in catalog.dimensions:
            raise ToolArgumentError(
                f"unknown filter dimension {dim!r}; available: {sorted(catalog.dimensions)}"
            )
        if not isinstance(value, str):
            raise ToolArgumentError(f"filter value for {dim!r} must be a string, got {value!r}")
        if "{" in value or "}" in value:
            raise ToolArgumentError(f"filter value for {dim!r} may not contain braces: {value!r}")

    d0 = _parse_date(start) if start else None
    d1 = _parse_date(end) if end else None
    if d0 and d1 and d0 > d1:
        raise ToolArgumentError(f"time_range start {start} is after end {end}")
    grain = grains[0].removeprefix("metric_time__") if grains else "day"
    if d0 and d0 != _period_start(d0, grain):
        raise ToolArgumentError(
            f"time_range start {start} does not align to the {grain} grain; "
            f"use {_period_start(d0, grain)} or group by a finer grain"
        )
    if d1 and d1 != _period_end(d1, grain):
        raise ToolArgumentError(
            f"time_range end {end} does not align to the {grain} grain; "
            f"use {_period_end(d1, grain)} or group by a finer grain"
        )
    return grain


def _check_coverage(start: str | None, end: str | None, grain: str, stamp: dict[str, str]) -> None:
    """Refuse a range reaching a period with no data at all: MetricFlow would answer 0 for it.
    Edge periods that the data covers partly are allowed; provenance.data_range says how much."""
    first, last = date.fromisoformat(stamp["data_start"]), date.fromisoformat(stamp["data_end"])
    lo, hi = _period_start(first, grain), _period_end(last, grain)
    if (start and date.fromisoformat(start) < lo) or (end and date.fromisoformat(end) > hi):
        raise ToolArgumentError(
            f"time_range {start}..{end} is outside the data ({first}..{last}); "
            f"by {grain}, use dates within {lo}..{hi}"
        )


@functools.cache
def _dimension_values(warehouse: Warehouse, built_at: str, metric: str, dim: str) -> frozenset:
    """Distinct values via `mf list dimension-values` (cached per warehouse build)."""
    out = run_cli(
        "mf", ["list", "dimension-values", "--metrics", metric, "--dimension", dim], warehouse
    )
    return frozenset(line[2:] for line in out.splitlines() if line.startswith("• "))


def _check_filter_values(
    filters: dict[str, str], metric: str, warehouse: Warehouse, built_at: str
) -> None:
    for dim, value in filters.items():
        values = _dimension_values(warehouse, built_at, metric, dim)
        if value not in values:
            by_lower = {v.lower(): v for v in values}
            close = difflib.get_close_matches(value.lower(), list(by_lower), n=3, cutoff=0.5)
            raise ToolArgumentError(
                f"filter {dim}={value!r} is not in the data; "
                f"closest values: {[by_lower[c] for c in close]}"
            )


def _where(dimension: str, value: str) -> str:
    quoted = value.replace("'", "''")
    return f"{{{{ Dimension('{dimension}') }}}} = '{quoted}'"


def read_snapshot_stamp(warehouse: Warehouse) -> dict[str, str]:
    """The snapshot the warehouse was BUILT from (dbt model warehouse_snapshot), not the raw
    snapshot.json, which can be newer than the last build.

    A failed `dbt build` can rebuild staging while skipping the fact and the stamp; the row
    counts then disagree with the stamp and this raises instead of mislabelling old numbers.
    """
    with duckdb.connect(str(warehouse.duckdb_path), read_only=True) as con:
        rows = con.execute(
            """SELECT snapshot_date, source_sha256, CAST(built_at AS VARCHAR), data_start,
                      data_end, dbt_invocation_id, staging_rows, fact_rows,
                      (SELECT count(*) FROM stg_complaints),
                      (SELECT count(*) FROM fct_complaints)
               FROM warehouse_snapshot"""
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"{warehouse.duckdb_path}: warehouse_snapshot has {len(rows)} rows")
    snapshot_date, sha, built_at, start, end, invocation, staging_rows, fact_rows, n_stg, n_fct = (
        rows[0]
    )
    if (n_stg, n_fct) != (staging_rows, fact_rows):
        raise RuntimeError(
            f"{warehouse.duckdb_path}: warehouse is inconsistent with its stamp "
            f"(staging {n_stg} vs {staging_rows}, fact {n_fct} vs {fact_rows} rows); "
            "the last dbt build probably failed, rebuild it"
        )
    return {
        "snapshot_date": snapshot_date,
        "source_sha256": sha,
        "built_at": built_at,
        "data_start": start,
        "data_end": end,
        "dbt_invocation_id": invocation,
    }


def _number(value: str) -> int | float | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return float(value)


def query_metric(
    metrics: list[str],
    group_by: list[str] | None = None,
    filters: dict[str, str] | None = None,
    time_range: tuple[str | None, str | None] | None = None,
    warehouse: Warehouse | None = None,
) -> MetricResult:
    """Query governed metrics via `mf query`. Filters are equality on dimensions (AND-ed);
    time_range is [start, end], both inclusive, as YYYY-MM-DD."""
    warehouse = warehouse or Warehouse()
    _check_types(metrics, group_by, filters, time_range)
    group_by = list(group_by or [])
    filters = dict(filters or {})
    start, end = time_range or (None, None)
    grain = _validate(load_catalog(warehouse), list(metrics), group_by, filters, start, end)
    snapshot = read_snapshot_stamp(warehouse)
    _check_coverage(start, end, grain, snapshot)
    _check_filter_values(filters, metrics[0], warehouse, snapshot["built_at"])

    args = ["query", "--metrics", ",".join(metrics)]
    if group_by:
        args += ["--group-by", ",".join(group_by), "--order", ",".join(group_by)]
    for dim, value in filters.items():
        args += ["--where", _where(dim, value)]
    if start:
        args += ["--start-time", start]
    if end:
        args += ["--end-time", end]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.csv"
        stdout = run_cli("mf", [*args, "--csv", str(out)], warehouse)
        if out.exists():
            with out.open(newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                raw = list(reader)
        elif "empty result set" in stdout:  # mf writes no CSV for zero rows
            columns, raw = [*group_by, *metrics], []
        else:
            raise RuntimeError(f"mf query wrote no CSV and reported no empty result:\n{stdout}")

    rows: list[dict[str, str | int | float | None]] = [
        {k: _number(v) if k in metrics else v for k, v in r.items()} for r in raw
    ]
    provenance = Provenance(
        metrics=list(metrics),
        group_by=group_by,
        filters=filters,
        time_range=(start, end),
        data_range=(snapshot["data_start"], snapshot["data_end"]),
        columns=columns,
        snapshot_date=snapshot["snapshot_date"],
        source_sha256=snapshot["source_sha256"],
    )
    logger.info("query_metric %s -> %d rows", provenance, len(rows))
    return MetricResult(rows=rows, provenance=provenance)
