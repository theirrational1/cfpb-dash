"""What the semantic layer exposes (from dbt's semantic manifest): the only valid tool names."""

import json
from dataclasses import dataclass

from core.warehouse import Warehouse

TIME_GRAINS = ("day", "week", "month", "quarter", "year")
MONTHS = {"month": 1, "quarter": 3, "year": 12}


@dataclass(frozen=True)
class PeriodRule:
    """A metric that only makes sense over time: the group-bys it can be queried at, and (for
    period-over-period metrics) how many months back it compares."""

    grains: frozenset[str]  # metric_time__<grain>
    offset_months: int | None


@dataclass(frozen=True)
class Catalog:
    metrics: frozenset[str]
    dimensions: frozenset[str]  # categorical, as entity__dimension
    time_grains: frozenset[str]  # metric_time__<grain>
    period_rules: dict[str, PeriodRule]


def _grain(name: str) -> frozenset[str]:
    return frozenset({f"metric_time__{name}"})


def load_catalog(warehouse: Warehouse) -> Catalog:
    path = warehouse.semantic_manifest
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run dbt build first")
    manifest = json.loads(path.read_text())
    dims: set[str] = set()
    for sm in manifest["semantic_models"]:
        [primary] = [e["name"] for e in sm["entities"] if e["type"] == "primary"]
        dims |= {f"{primary}__{d['name']}" for d in sm["dimensions"] if d["type"] == "categorical"}

    by_name = {m["name"]: m for m in manifest["metrics"]}

    def to_date_grain(metric: dict) -> str | None:
        params = metric["type_params"].get("cumulative_type_params") or {}
        return params.get("grain_to_date")

    rules: dict[str, PeriodRule] = {}
    for m in manifest["metrics"]:
        grain = to_date_grain(m)
        if grain:  # period to date: by day (running) or at its own grain (period total)
            rules[m["name"]] = PeriodRule(_grain("day") | _grain(grain), None)
        for inp in m["type_params"].get("metrics") or []:
            offset = inp.get("offset_window")
            if offset:
                base_grain = to_date_grain(by_name[inp["name"]]) or offset["granularity"]
                months = offset["count"] * MONTHS[offset["granularity"]]
                rules[m["name"]] = PeriodRule(_grain(base_grain), months)
    return Catalog(
        metrics=frozenset(by_name),
        dimensions=frozenset(dims),
        time_grains=frozenset(f"metric_time__{g}" for g in TIME_GRAINS),
        period_rules=rules,
    )
