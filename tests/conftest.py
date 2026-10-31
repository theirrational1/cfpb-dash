import hashlib
import json
from pathlib import Path

import pytest

FIXTURE_BYTES = b"complaint_id,company\n1,Acme Bank\n"


@pytest.fixture
def tmp_raw_dir(tmp_path: Path) -> Path:
    """A tiny raw landing dir: one file plus a MANIFEST.json that matches it."""
    data_file = tmp_path / "bulk" / "sample.csv"
    data_file.parent.mkdir()
    data_file.write_bytes(FIXTURE_BYTES)
    manifest = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "notes": "fixture",
        "files": [
            {
                "path": "bulk/sample.csv",
                "source": "fixture",
                "source_url": "https://example.invalid/sample.csv",
                "retrieved_at": "2026-01-01",
                "size_bytes": len(FIXTURE_BYTES),
                "sha256": hashlib.sha256(FIXTURE_BYTES).hexdigest(),
            }
        ],
    }
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return tmp_path


@pytest.fixture
def make_interim(tmp_path: Path):
    """Factory: write tiny bulk/narratives Parquet (all text, real column names) + INTERIM.json.

    Rows are dicts keyed by raw column name; missing keys become NULL.
    """
    import duckdb

    from ingestion.raw_csv import BULK_COLUMNS, NARRATIVE_COLUMNS

    def build(bulk_rows: list[dict], narrative_rows: list[dict]) -> Path:
        root = tmp_path / "interim"
        con = duckdb.connect()
        for name, columns, rows in (
            ("bulk", BULK_COLUMNS, bulk_rows),
            ("narratives", NARRATIVE_COLUMNS, narrative_rows),
        ):
            (root / name).mkdir(parents=True)
            cols = ", ".join(f'"{c}" VARCHAR' for c in columns)
            con.execute(f"CREATE TABLE {name} ({cols}, source_file VARCHAR)")
            if rows:
                marks = ", ".join("?" for _ in range(len(columns) + 1))
                con.executemany(
                    f"INSERT INTO {name} VALUES ({marks})",
                    [[r.get(c) for c in columns] + [r.get("source_file", "f.zip")] for r in rows],
                )
            con.execute(f"COPY {name} TO '{root / name / 'part.parquet'}' (FORMAT parquet)")
        source = {"path": "bulk/x.csv.zip", "sha256": "0" * 64, "retrieved_at": "2026-01-01"}
        info = {
            "built_at": "2026-01-01T00:00:00+00:00",
            "bulk": {"parquet_dir": "bulk/", "rows": len(bulk_rows), "sources": [source]},
            "narratives": {
                "parquet_dir": "narratives/",
                "rows": len(narrative_rows),
                "sources": [],
            },
        }
        (root / "INTERIM.json").write_text(json.dumps(info, indent=2) + "\n")
        return root

    return build


FIXTURE_CSV = Path(__file__).parent / "fixtures" / "complaints_sample.csv"


@pytest.fixture(scope="session")
def fixture_csv() -> Path:
    """~1K real credit card complaints (3 issuers, 2025-01..2026-06), raw bulk header."""
    return FIXTURE_CSV


def build_warehouse(root: Path, csv_path: Path, snapshot_date: str, project_dir: Path):
    """Ingest `csv_path` and `dbt build` into a warehouse at `root` (shared test helper)."""
    from core.warehouse import Warehouse, run_cli
    from ingestion.bulk import ingest

    wh = Warehouse(root, project_dir=project_dir)
    ingest(csv_path, wh.raw_parquet, snapshot_date=snapshot_date, work_dir=root / "work")
    run_cli("dbt", ["build"], wh)
    return wh


@pytest.fixture(scope="session")
def dbt_project(tmp_path_factory) -> Path:
    """A private copy of dbt/ so test builds never touch the real dbt/target."""
    import shutil

    from core.warehouse import DBT_DIR

    dest = tmp_path_factory.mktemp("dbt_project") / "dbt"
    shutil.copytree(DBT_DIR, dest, ignore=shutil.ignore_patterns("target", "logs", ".user.yml"))
    return dest


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory, fixture_csv, dbt_project):
    """Fixture CSV -> raw Parquet -> `dbt build`, once per test session."""
    return build_warehouse(
        tmp_path_factory.mktemp("warehouse"), fixture_csv, "2026-10-31", dbt_project
    )
