"""M2-10: freeze a dated, self-contained, checksummed copy of the warehouse for evals."""

import json
import os
import stat

import pytest

from agent.tools.query_metric import query_metric, read_snapshot_stamp
from core.warehouse import Warehouse
from ingestion.snapshot import freeze, resolve_eval_warehouse, verify_snapshot

CITI = {"complaint__company": "CITIBANK, N.A."}


def _count(wh) -> object:
    r = query_metric(["complaint_count"], filters=CITI, time_range=("2026-03-01", "2026-03-31"),
                     warehouse=wh)  # fmt: skip
    return r.rows[0]["complaint_count"], r.provenance.snapshot_date


def test_freeze_makes_a_self_contained_checksummed_read_only_copy(warehouse, tmp_path):
    frozen = freeze(warehouse, tmp_path / "snapshots")

    assert frozen.root == tmp_path / "snapshots" / "2026-10-31"
    assert verify_snapshot(frozen.root) == []
    info = json.loads((frozen.root / "SNAPSHOT.json").read_text())
    assert info["snapshot_date"] == "2026-10-31"
    assert set(info["files"]) == {"cfpb.duckdb", "dbt/target/semantic_manifest.json"}
    assert not os.stat(frozen.duckdb_path).st_mode & stat.S_IWUSR, "frozen DuckDB is read-only"
    # answers from the frozen copy match the live warehouse, through its own project copy
    assert frozen.project_dir == frozen.root / "dbt"
    assert _count(frozen) == _count(warehouse)
    assert read_snapshot_stamp(frozen)["built_at"] == read_snapshot_stamp(warehouse)["built_at"]


def test_freeze_refuses_to_overwrite_and_verify_catches_tampering(warehouse, tmp_path):
    frozen = freeze(warehouse, tmp_path / "snapshots")
    with pytest.raises(FileExistsError):
        freeze(warehouse, tmp_path / "snapshots")
    manifest = frozen.root / "dbt" / "target" / "semantic_manifest.json"
    os.chmod(manifest, 0o644)
    manifest.write_text(manifest.read_text() + " ")
    assert verify_snapshot(frozen.root) == ["sha256 mismatch: dbt/target/semantic_manifest.json"]


def test_evals_use_the_newest_frozen_snapshot_and_refuse_a_live_warehouse(warehouse, tmp_path):
    snapshots = tmp_path / "snapshots"
    frozen = freeze(warehouse, snapshots)
    assert resolve_eval_warehouse(None, snapshots) == frozen
    assert resolve_eval_warehouse(frozen.root, snapshots) == frozen
    with pytest.raises(ValueError, match="not a frozen snapshot"):
        resolve_eval_warehouse(warehouse.root, snapshots)
    with pytest.raises(FileNotFoundError, match="no frozen snapshot"):
        resolve_eval_warehouse(None, tmp_path / "none")


def test_a_frozen_snapshot_that_fails_verification_is_refused(warehouse, tmp_path):
    frozen = freeze(warehouse, tmp_path / "snapshots")
    os.chmod(frozen.duckdb_path, 0o644)
    with frozen.duckdb_path.open("ab") as f:
        f.write(b"x")
    with pytest.raises(ValueError, match="fails verification"):
        resolve_eval_warehouse(frozen.root, tmp_path / "snapshots")


def test_live_default_is_not_frozen():
    assert not (Warehouse().root / "SNAPSHOT.json").exists()
