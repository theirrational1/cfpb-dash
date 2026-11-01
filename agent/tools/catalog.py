"""What the semantic layer exposes (from dbt's semantic manifest): the only valid tool names."""

import json
from dataclasses import dataclass

from core.warehouse import Warehouse

TIME_GRAINS = ("day", "week", "month", "quarter", "year")
# grains that tile an offset window exactly (a period-over-period metric needs one of these)
GRAINS_DIVIDING = {
    "day": {"day"},
    "week": {"day", "week"},
    "month": {"day", "month"},
    "quarter": {"day", "month", "quarter"},
    "year": {"day", "month", "quarter", "year"},
}


@dataclass(frozen=True)
class Catalog:
    metrics: frozenset[str]
    dimensions: frozenset[str]  # categorical, as entity__dimension
    time_grains: frozenset[str]  # metric_time__<grain>
    # period-over-period metrics -> the metric_time__<grain> group-bys they can be queried at
    offset_grains: dict[str, frozenset[str]]


def load_catalog(warehouse: Warehouse) -> Catalog:
    path = warehouse.semantic_manifest
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run dbt build first")
    manifest = json.loads(path.read_text())
    dims: set[str] = set()
    for sm in manifest["semantic_models"]:
        [primary] = [e["name"] for e in sm["entities"] if e["type"] == "primary"]
        dims |= {f"{primary}__{d['name']}" for d in sm["dimensions"] if d["type"] == "categorical"}
    offset_grains: dict[str, frozenset[str]] = {}
    for m in manifest["metrics"]:
        for inp in m["type_params"].get("metrics") or []:
            if inp.get("offset_window"):
                grains = GRAINS_DIVIDING[inp["offset_window"]["granularity"]]
                offset_grains[m["name"]] = frozenset(f"metric_time__{g}" for g in grains)
    return Catalog(
        metrics=frozenset(m["name"] for m in manifest["metrics"]),
        dimensions=frozenset(dims),
        time_grains=frozenset(f"metric_time__{g}" for g in TIME_GRAINS),
        offset_grains=offset_grains,
    )
