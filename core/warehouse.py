"""One place that knows where a warehouse lives and how to run dbt / MetricFlow against it.

Python callers (tests, tools, app) pass absolute paths through the environment, so dbt, `mf`
and DuckDB all point at the same files. CLI users get the same defaults from dbt.env.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "dbt"
DEFAULT_ROOT = REPO_ROOT / "data" / "warehouse"


@dataclass(frozen=True)
class Warehouse:
    root: Path = DEFAULT_ROOT

    @property
    def duckdb_path(self) -> Path:
        return self.root / "cfpb.duckdb"

    @property
    def raw_parquet(self) -> Path:
        return self.root / "raw" / "complaints.parquet"

    @property
    def snapshot_json(self) -> Path:
        return self.raw_parquet.parent / "snapshot.json"

    def env(self) -> dict[str, str]:
        return {
            "DBT_PROJECT_DIR": str(DBT_DIR),
            "DBT_PROFILES_DIR": str(DBT_DIR),
            "DBT_TARGET_PATH": str(self.root / "dbt_target"),
            "DBT_LOG_PATH": str(self.root / "dbt_logs"),
            "CFPB_DUCKDB_PATH": str(self.duckdb_path),
            "CFPB_RAW_PARQUET": str(self.raw_parquet),
        }


def run_cli(tool: str, args: list[str], warehouse: Warehouse) -> str:
    """Run `dbt` or `mf` from this venv against `warehouse`. Raises with the tool's output."""
    if tool not in ("dbt", "mf"):
        raise ValueError(f"unknown tool {tool!r}")
    exe = Path(sys.executable).parent / tool
    env = {"PATH": str(exe.parent), "HOME": str(Path.home()), **warehouse.env()}
    logger.info("running %s %s (warehouse %s)", tool, " ".join(args), warehouse.root)
    proc = subprocess.run([str(exe), *args], env=env, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{tool} {' '.join(args)} failed (exit {proc.returncode}):\n"
            f"{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    return proc.stdout
