"""M2-03: incremental API pull. Recorded real API responses (tests/fixtures/api/) are served
by a fake transport: no network in tests."""

import json
from datetime import UTC, date, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from ingestion.incremental import (
    StaleDataError,
    TruncatedExportError,
    pull,
    pull_window,
)
from ingestion.manifest import load_manifest, sha256_file
from ingestion.schema_check import SchemaDriftError

API_FIXTURES = Path(__file__).parent / "fixtures" / "api"
DAYS = [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]
NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


class FakeApi:
    """Serves the recorded day CSVs and count responses; records every URL requested."""

    def __init__(self, meta_override=None, count_offset=0, csv_edit=None, fail_first=None):
        self.urls: list[str] = []
        self.meta_override = meta_override or {}
        self.count_offset = count_offset
        self.csv_edit = csv_edit
        self.fail_first = list(fail_first or [])

    def _csv(self, day: str) -> bytes:
        text = (API_FIXTURES / f"citi_cc_{day}.csv").read_text()
        return (self.csv_edit(text) if self.csv_edit else text).encode()

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.fail_first:
            raise HTTPError(url, self.fail_first.pop(0), "fail", Message(), BytesIO())
        q = parse_qs(urlparse(url).query)
        day = q["date_received_min"][0]
        assert q["date_received_max"] == [day], "one day per request"
        if q.get("format") == ["csv"]:
            return self._csv(day)
        recorded = json.loads((API_FIXTURES / "count_response.json").read_text())
        n = self._csv(day).decode().count("\n") - 1 + self.count_offset
        recorded["hits"]["total"]["value"] = n
        recorded["_meta"] |= self.meta_override
        return json.dumps(recorded).encode()


@pytest.fixture
def raw_dir(tmp_path):
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"manifest_version": 1, "generated_at": "x", "notes": "t", "files": []})
    )
    return tmp_path


def test_window_repulls_15_days_before_coverage_end_through_today():
    days = pull_window(coverage_end=date(2026, 10, 30), today=date(2026, 11, 1))
    assert days[0] == date(2026, 10, 15) and days[-1] == date(2026, 11, 1) and len(days) == 18
    # a stale bulk (coverage ended long ago) still pulls the whole gap
    assert pull_window(date(2026, 9, 1), date(2026, 11, 1))[0] == date(2026, 8, 17)


def test_pull_lands_immutable_day_files_with_manifest_entries(raw_dir):
    api = FakeApi()
    out = pull(DAYS, raw_dir, raw_dir / "MANIFEST.json", fetch=api, now=NOW, sleep=lambda s: None)

    assert out == raw_dir / "api" / "20261101T060000Z"
    info = json.loads((out / "pull.json").read_text())
    assert info["days"] == {"2026-10-20": 13, "2026-10-21": 10, "2026-10-22": 7}
    assert info["pulled_at"] == "2026-11-01T06:00:00+00:00"
    assert info["last_indexed"] == "2026-10-31T12:00:00-05:00"
    entries = {e["path"]: e for e in load_manifest(raw_dir / "MANIFEST.json")["files"]}
    for day in ("2026-10-20", "2026-10-21", "2026-10-22"):
        e = entries[f"api/20261101T060000Z/{day}.csv"]
        assert e["sha256"] == sha256_file(out / f"{day}.csv")
        assert "date_received_min=" + day in e["source_url"]
    assert "api/20261101T060000Z/pull.json" in entries
    with pytest.raises(FileExistsError):
        pull(DAYS, raw_dir, raw_dir / "MANIFEST.json", fetch=api, now=NOW, sleep=lambda s: None)


@pytest.mark.parametrize(
    ("api", "error", "match"),
    [
        (FakeApi(meta_override={"is_data_stale": True}), StaleDataError, "stale"),
        (FakeApi(meta_override={"has_data_issue": True}), StaleDataError, "data issue"),
        (FakeApi(count_offset=5), TruncatedExportError, "13 rows, the API counts 18"),
        (
            FakeApi(csv_edit=lambda t: t.replace("Timely response?", "Timely", 1)),
            SchemaDriftError,
            r"'Timely response\?' -> 'Timely'",
        ),
    ],
)
def test_pull_fails_loudly_and_lands_nothing(raw_dir, api, error, match):
    with pytest.raises(error, match=match):
        pull([date(2026, 10, 20)], raw_dir, raw_dir / "MANIFEST.json", fetch=api, now=NOW,
             sleep=lambda s: None)  # fmt: skip
    assert not (raw_dir / "api" / "20261101T060000Z" / "pull.json").exists()
    assert load_manifest(raw_dir / "MANIFEST.json")["files"] == []


def test_transient_errors_are_retried_and_others_raise(raw_dir):
    sleeps: list[float] = []
    api = FakeApi(fail_first=[503, 429])
    pull(DAYS[:1], raw_dir, raw_dir / "MANIFEST.json", fetch=api, now=NOW, sleep=sleeps.append)
    assert sleeps == [2, 4, 0.5]  # two backoffs, then the polite pause after the day
    with pytest.raises(HTTPError):
        pull(DAYS[:1], raw_dir, raw_dir / "MANIFEST.json", fetch=FakeApi(fail_first=[404]),
             now=datetime(2026, 11, 2, tzinfo=UTC), sleep=lambda s: None)  # fmt: skip


def _con():
    import duckdb

    return duckdb.connect()


def test_build_normalizes_pulls_into_parquet(raw_dir, tmp_path):
    from ingestion.incremental import build

    pull(DAYS, raw_dir, raw_dir / "MANIFEST.json", fetch=FakeApi(), now=NOW, sleep=lambda s: None)
    out = tmp_path / "wh" / "api_complaints.parquet"
    days_out = tmp_path / "wh" / "api_pull_days.parquet"
    info = build(raw_dir / "api", out, days_out)

    assert info == {"pulls": 1, "rows": 30, "latest_pulled_at": "2026-11-01T06:00:00+00:00"}
    con = _con()
    row = con.execute(
        f"""SELECT count(*), min("Date received"), max("Date sent to company"),
                   count(*) FILTER (WHERE "ZIP code" IS NULL),
                   count(*) FILTER (WHERE "Tags" = 'None'), min(pulled_at)
            FROM read_parquet('{out}')"""
    ).fetchone()
    assert row is not None
    assert row[:5] == (30, "2026-10-20", row[2], 30, 0)
    assert len(row[2]) == 10  # timestamps cut to YYYY-MM-DD, as in bulk
    pulled = con.execute(f"SELECT day, rows FROM read_parquet('{days_out}') ORDER BY 1").fetchall()
    assert pulled == [("2026-10-20", 13), ("2026-10-21", 10), ("2026-10-22", 7)]


def test_build_with_no_pulls_writes_empty_tables(tmp_path):
    from ingestion.incremental import build

    out, days_out = tmp_path / "a.parquet", tmp_path / "d.parquet"
    assert build(tmp_path / "missing", out, days_out)["rows"] == 0
    assert _con().execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone() == (0,)
    assert _con().execute(f"SELECT count(*) FROM read_parquet('{days_out}')").fetchone() == (0,)


def test_build_skips_incomplete_pulls(raw_dir, tmp_path):
    from ingestion.incremental import build

    partial = raw_dir / "api" / "20261102T000000Z"
    partial.mkdir(parents=True)
    (partial / "2026-10-20.csv").write_text((API_FIXTURES / "citi_cc_2026-10-20.csv").read_text())
    assert build(raw_dir / "api", tmp_path / "a.parquet", tmp_path / "d.parquet")["pulls"] == 0
