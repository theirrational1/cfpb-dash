"""query_metric: the only path to numbers for the agent and the app (governed MetricFlow metrics).

Public tool signature (AGENTS.md: ask before changing it).
"""

import csv
import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.warehouse import Warehouse, run_cli

logger = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Provenance:
    metrics: list[str]
    group_by: list[str]
    filters: dict[str, str]
    time_range: tuple[str | None, str | None]
    snapshot_date: str
    source_sha256: str


@dataclass(frozen=True)
class MetricResult:
    rows: list[dict[str, str | int | float | None]]
    provenance: Provenance
    columns: list[str] = field(default_factory=list)


def _check_name(kind: str, value: str) -> str:
    if not NAME.fullmatch(value):
        raise ValueError(f"invalid {kind} name {value!r}")
    return value


def _where(dimension: str, value: str) -> str:
    _check_name("dimension", dimension)
    if "{" in value or "}" in value:
        raise ValueError(f"filter value for {dimension!r} may not contain braces: {value!r}")
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
    """Query governed metrics via `mf query`. Filters are equality on dimensions (AND-ed)."""
    warehouse = warehouse or Warehouse()
    group_by = group_by or []
    filters = filters or {}
    start, end = time_range or (None, None)
    for m in metrics:
        _check_name("metric", m)
    for g in group_by:
        _check_name("group_by", g)

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
        group_by=list(group_by),
        filters=dict(filters),
        time_range=(start, end),
        snapshot_date=snapshot["snapshot_date"],
        source_sha256=snapshot["source_sha256"],
    )
    logger.info("query_metric %s -> %d rows", provenance, len(rows))
    return MetricResult(rows=rows, provenance=provenance, columns=columns)
