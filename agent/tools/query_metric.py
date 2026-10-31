"""query_metric: the only path to numbers for the agent and the app (governed MetricFlow metrics).

Public tool (AGENTS.md: ask before changing it). Arguments that MetricFlow would silently
reinterpret are refused with ToolArgumentError rather than answered with a wrong number:
time filters (use time_range), partial or inverted dates, ranges not aligned to a grouped time
grain (MetricFlow widens them to the grain), and bare `metric_time`.
"""

import csv
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from agent.tools.catalog import Catalog, load_catalog
from core.warehouse import Warehouse, run_cli

logger = logging.getLogger(__name__)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ToolArgumentError(ValueError):
    """The caller (usually the model) asked for something the governed layer can't answer as-is."""


@dataclass(frozen=True)
class Provenance:
    metrics: list[str]
    group_by: list[str]
    filters: dict[str, str]
    time_range: tuple[str | None, str | None]
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
    if grain == "week":
        return _period_start(d, grain) + timedelta(days=6)
    if grain in ("month", "quarter", "year"):
        months = {"month": 1, "quarter": 3, "year": 12}[grain]
        start = _period_start(d, grain)
        y, m = divmod(start.month - 1 + months, 12)
        return start.replace(year=start.year + y, month=m + 1) - timedelta(days=1)
    return d


def _validate(
    catalog: Catalog,
    metrics: list[str],
    group_by: list[str],
    filters: dict[str, str],
    start: str | None,
    end: str | None,
) -> None:
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


def _where(dimension: str, value: str) -> str:
    quoted = value.replace("'", "''")
    return f"{{{{ Dimension('{dimension}') }}}} = '{quoted}'"


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
    group_by = list(group_by or [])
    filters = dict(filters or {})
    start, end = time_range or (None, None)
    _validate(load_catalog(warehouse), list(metrics), group_by, filters, start, end)

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
        run_cli("mf", [*args, "--csv", str(out)], warehouse)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            columns = list(reader.fieldnames or [])
            raw = list(reader)

    rows: list[dict[str, str | int | float | None]] = [
        {k: _number(v) if k in metrics else v for k, v in r.items()} for r in raw
    ]
    snapshot = json.loads(warehouse.snapshot_json.read_text())
    provenance = Provenance(
        metrics=list(metrics),
        group_by=group_by,
        filters=filters,
        time_range=(start, end),
        columns=columns,
        snapshot_date=snapshot["snapshot_date"],
        source_sha256=snapshot["source_sha256"],
    )
    logger.info("query_metric %s -> %d rows", provenance, len(rows))
    return MetricResult(rows=rows, provenance=provenance)
