"""Frozen eval snapshots (M2-10): a dated, self-contained, checksummed, read-only copy.

data/snapshots/<snapshot_date>/ holds cfpb.duckdb (every model is a table, so the copy needs
no raw files), the dbt project with target/semantic_manifest.json (what `mf` reads), and
SNAPSHOT.json with the stamp and sha256s. Evals run only against these (AGENTS.md).

Run: uv run python -m ingestion.snapshot
"""

import json
import logging
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

from agent.tools.query_metric import read_snapshot_stamp
from core.log import configure_logging
from core.warehouse import REPO_ROOT, Warehouse
from ingestion.manifest import sha256_file

logger = logging.getLogger(__name__)

SNAPSHOTS = REPO_ROOT / "data" / "snapshots"
CHECKED = ("cfpb.duckdb", "dbt/target/semantic_manifest.json")


def _frozen(root: Path) -> Warehouse:
    return Warehouse(root, project_dir=root / "dbt")


def freeze(warehouse: Warehouse, snapshots: Path = SNAPSHOTS) -> Warehouse:
    stamp = read_snapshot_stamp(warehouse)  # refuses an inconsistent (half-built) warehouse
    wal = warehouse.duckdb_path.with_name(warehouse.duckdb_path.name + ".wal")
    if wal.exists():
        raise RuntimeError(f"{wal} exists: a writer has not checkpointed; close it first")
    dest = snapshots / stamp["snapshot_date"]
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; snapshots are immutable")

    tmp = snapshots / f".{dest.name}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    shutil.copy2(warehouse.duckdb_path, tmp / "cfpb.duckdb")
    shutil.copytree(warehouse.project_dir, tmp / "dbt",
                    ignore=shutil.ignore_patterns("logs", ".user.yml"))  # fmt: skip
    files = {rel: {"sha256": sha256_file(tmp / rel), "size_bytes": (tmp / rel).stat().st_size}
             for rel in CHECKED}  # fmt: skip
    info = {**stamp, "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "frozen_from": str(warehouse.root), "files": files}  # fmt: skip
    (tmp / "SNAPSHOT.json").write_text(json.dumps(info, indent=2) + "\n")
    for rel in (*CHECKED, "SNAPSHOT.json"):
        os.chmod(tmp / rel, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    tmp.rename(dest)
    logger.info("froze %s -> %s", warehouse.root, dest)
    return _frozen(dest)


def verify_snapshot(root: Path) -> list[str]:
    info = json.loads((root / "SNAPSHOT.json").read_text())
    problems = []
    for rel, expected in info["files"].items():
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif sha256_file(path) != expected["sha256"]:
            problems.append(f"sha256 mismatch: {rel}")
    for p in problems:
        logger.error("%s: %s", root, p)
    return problems


def resolve_eval_warehouse(path: Path | None, snapshots: Path = SNAPSHOTS) -> Warehouse:
    """The newest frozen snapshot, or `path` if it is one. A live warehouse is refused."""
    if path is None:
        dated = sorted(p for p in snapshots.glob("*") if (p / "SNAPSHOT.json").is_file()) if (
            snapshots.is_dir()) else []  # fmt: skip
        if not dated:
            raise FileNotFoundError(
                f"no frozen snapshot in {snapshots}; run python -m ingestion.snapshot"
            )
        path = dated[-1]
    if not (path / "SNAPSHOT.json").is_file():
        raise ValueError(f"{path} is not a frozen snapshot; evals run only on frozen snapshots")
    problems = verify_snapshot(path)
    if problems:
        raise ValueError(f"{path} fails verification: {problems}")
    return _frozen(path)


def main() -> None:
    configure_logging()
    frozen = freeze(Warehouse.from_env())
    print(frozen.root)


if __name__ == "__main__":
    main()
