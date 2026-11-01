"""Incremental pull from the CFPB Search API: one CSV export per received-date day.

Each run re-pulls the trailing LOOKBACK_DAYS before the last covered day through today, so
late-arriving complaints and status changes (In progress -> closed) within the window are
picked up; older changes arrive with the next bulk capture (decision log, M2-03).

The day export uses the bulk CSV header; it writes dates as timestamps and nulls as the
literal 'None' (normalized at build time). Each day's row count is checked against the API's
own count, and the pull stops if the API reports stale data or a data issue.
Landed files are immutable: data/raw/api/<pulled_at>/<day>.csv + pull.json, each in
MANIFEST.json.

Run: uv run python -m ingestion.incremental
"""

import argparse
import csv
import io
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import duckdb

from core.log import configure_logging
from core.warehouse import REPO_ROOT, Warehouse
from ingestion.manifest import append_entry, sha256_file
from ingestion.raw_csv import BULK_COLUMNS, sql_str
from ingestion.schema_check import check_fields

logger = logging.getLogger(__name__)

RAW_DIR = REPO_ROOT / "data" / "raw"

API_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
SOURCE = "CFPB Consumer Complaint Database — Search API (CSV export, one day per file)"
LOOKBACK_DAYS = 15
EASTERN = ZoneInfo("America/New_York")  # CFPB dates complaints and indexes in US Eastern time
RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 5
BACKOFF_S = 30  # doubles per retry unless the server sends Retry-After
REQUEST_PAUSE_S = 3  # be polite: requests are sequential with a pause (the API rate-limits)

Fetch = Callable[[str], bytes]


class StaleDataError(RuntimeError):
    pass


class TruncatedExportError(RuntimeError):
    pass


def http_get(url: str) -> bytes:
    with urlopen(url, timeout=300) as resp:
        return resp.read()


def _get(url: str, fetch: Fetch, sleep: Callable[[float], None]) -> bytes:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fetch(url)
        except HTTPError as e:
            if e.code not in RETRY_STATUSES or attempt == ATTEMPTS:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            wait = (
                int(retry_after)
                if retry_after and retry_after.isdigit()
                else (BACKOFF_S * 2 ** (attempt - 1))
            )
            logger.warning("HTTP %d for %s; retry %d in %ds", e.code, url, attempt, wait)
            sleep(wait)
    raise AssertionError("unreachable")


def _url(day: date, **extra: str) -> str:
    d = day.isoformat()
    return API_URL + "?" + urlencode({"date_received_min": d, "date_received_max": d,
                                      "no_aggs": "true", **extra})  # fmt: skip


def pull_window(coverage_end: date, today: date, lookback: int = LOOKBACK_DAYS) -> list[date]:
    """Every day from `lookback` days before the last covered day through today."""
    start = min(coverage_end, today) - timedelta(days=lookback)
    return [start + timedelta(days=i) for i in range((today - start).days + 1)]


def _count(day: date, fetch: Fetch, sleep: Callable[[float], None]) -> tuple[int, dict]:
    body = json.loads(_get(_url(day, size="0"), fetch, sleep))
    meta = body["_meta"]
    if meta["is_data_stale"]:
        raise StaleDataError(f"API reports stale data (last_indexed {meta['last_indexed']})")
    if meta["has_data_issue"]:
        raise StaleDataError(f"API reports a data issue (last_updated {meta['last_updated']})")
    return body["hits"]["total"]["value"], meta


def pull(
    days: list[date],
    raw_dir: Path,
    manifest_path: Path,
    fetch: Fetch = http_get,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Fetch and check every day first; only then land the files and manifest entries."""
    now = now or datetime.now(UTC)
    out = raw_dir / "api" / now.strftime("%Y%m%dT%H%M%SZ")
    if out.exists():
        raise FileExistsError(f"{out} already exists; raw files are immutable")

    fetched: dict[date, tuple[str, bytes, int]] = {}
    meta: dict = {}
    for day in days:
        expected, meta = _count(day, fetch, sleep)
        url = _url(day, format="csv")
        body = _get(url, fetch, sleep)
        reader = csv.reader(io.StringIO(body.decode("utf-8"), newline=""))
        check_fields(next(reader), BULK_COLUMNS, f"API export {day}")
        rows = sum(1 for _ in reader)
        if rows != expected:
            raise TruncatedExportError(
                f"API export for {day} has {rows} rows, the API counts {expected}"
            )
        fetched[day] = (url, body, rows)
        logger.info("pulled %s: %d rows", day, rows)
        sleep(REQUEST_PAUSE_S)

    out.mkdir(parents=True)
    stamp = now.isoformat(timespec="seconds")
    info = {"pulled_at": stamp, "last_indexed": meta.get("last_indexed"),
            "last_updated": meta.get("last_updated"), "days": {}}  # fmt: skip
    for day, (url, body, rows) in fetched.items():
        path = out / f"{day.isoformat()}.csv"
        path.write_bytes(body)
        info["days"][day.isoformat()] = rows
        _record(manifest_path, path, url, stamp)
    (out / "pull.json").write_text(json.dumps(info, indent=2) + "\n")
    _record(manifest_path, out / "pull.json", API_URL, stamp)
    logger.info("pull %s: %d days, %d rows", out.name, len(days), sum(info["days"].values()))
    return out


def _record(manifest_path: Path, path: Path, url: str, stamp: str) -> None:
    append_entry(
        manifest_path,
        {
            "path": str(path.relative_to(manifest_path.parent)),
            "source": SOURCE,
            "source_url": url,
            "retrieved_at": stamp[:10],
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        },  # fmt: skip
        generated_at=stamp,
    )


def _normalized_select(csv_path: Path, pulled_at: str, as_of: str, day: str) -> str:
    """API export -> bulk representation: 'None' -> NULL, timestamps -> YYYY-MM-DD."""
    cols = []
    for c in BULK_COLUMNS:
        expr = f"""nullif("{c}", 'None')"""
        if c.startswith("Date"):
            expr = f"left({expr}, 10)"
        cols.append(f'{expr} AS "{c}"')
    return (
        f"SELECT {', '.join(cols)}, CAST({sql_str(pulled_at)} AS TIMESTAMPTZ) AS pulled_at, "
        f"CAST({sql_str(as_of)} AS TIMESTAMPTZ) AS as_of, {sql_str(day)} AS pulled_day "
        f"FROM read_csv({sql_str(csv_path)}, all_varchar=true, header=true, strict_mode=true)"
    )


def build(api_root: Path, out: Path, days_out: Path) -> dict:
    """Every complete pull (has pull.json) -> `out` (rows, bulk column names, plus pulled_at,
    as_of and pulled_day) and `days_out` (one row per pulled day, including empty days, so dbt
    can tell which days a pull covered). Both are replaced back to back.

    as_of = the API's last_indexed: when CFPB produced the data this pull saw (staging orders
    versions by it); as_of_date_et is its US Eastern date, the provenance snapshot date."""
    pulls = sorted(p.parent for p in api_root.glob("*/pull.json")) if api_root.is_dir() else []
    con = duckdb.connect()
    selects, days = [], []
    for pull_dir in pulls:
        info = json.loads((pull_dir / "pull.json").read_text())
        if not info.get("last_indexed"):
            raise ValueError(f"{pull_dir}/pull.json has no last_indexed")
        as_of = datetime.fromisoformat(info["last_indexed"])
        as_of_et = as_of.astimezone(EASTERN).date().isoformat()
        for day, rows in info["days"].items():
            path = pull_dir / f"{day}.csv"
            with path.open(newline="", encoding="utf-8") as f:
                check_fields(next(csv.reader(f)), BULK_COLUMNS, str(path))
            selects.append(_normalized_select(path, info["pulled_at"], info["last_indexed"], day))
            days.append((info["pulled_at"], info["last_indexed"], as_of_et, day, rows))
    empty = ", ".join(f'NULL::VARCHAR AS "{c}"' for c in BULK_COLUMNS)
    rows_sql = " UNION ALL ".join(selects) or (
        f"SELECT {empty}, NULL::TIMESTAMPTZ AS pulled_at, NULL::TIMESTAMPTZ AS as_of, "
        "NULL::VARCHAR AS pulled_day LIMIT 0"
    )
    con.execute(
        "CREATE TABLE pull_days (pulled_at TIMESTAMPTZ, as_of TIMESTAMPTZ, as_of_date_et VARCHAR,"
        " day VARCHAR, rows BIGINT)"
    )
    if days:
        con.executemany("INSERT INTO pull_days VALUES (?, ?, ?, ?, ?)", days)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp, days_tmp = out.with_name(out.name + ".tmp"), days_out.with_name(days_out.name + ".tmp")
    con.execute(f"COPY ({rows_sql}) TO {sql_str(tmp)} (FORMAT parquet)")
    con.execute(f"COPY pull_days TO {sql_str(days_tmp)} (FORMAT parquet)")
    written = con.execute(f"SELECT count(*) FROM read_parquet({sql_str(tmp)})").fetchone()
    expected = sum(d[-1] for d in days)
    if written is None or written[0] != expected:
        raise ValueError(f"API parquet has {written} rows, pull.json files say {expected}")
    os.replace(tmp, out)
    os.replace(days_tmp, days_out)
    latest = json.loads((pulls[-1] / "pull.json").read_text())["pulled_at"] if pulls else None
    logger.info("built %s: %d pulls, %d rows", out, len(pulls), expected)
    return {"pulls": len(pulls), "rows": expected, "latest_pulled_at": latest}


def coverage_end(warehouse: Warehouse) -> date:
    """The latest received day already covered by the bulk file or any pull."""
    con = duckdb.connect()
    row = con.execute(
        f"""SELECT greatest(
                (SELECT max(CAST("Date received" AS DATE))
                 FROM read_parquet({sql_str(warehouse.raw_parquet)})),
                (SELECT max(CAST(day AS DATE))
                 FROM read_parquet({sql_str(warehouse.api_pull_days)})))"""
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"{warehouse.raw_parquet}: no received dates; ingest the bulk file first")
    return row[0]


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", action="store_true", help="rebuild Parquet, no pull")
    args = parser.parse_args()
    wh = Warehouse.from_env()
    if not args.build_only:
        if not wh.api_pull_days.exists():
            build(RAW_DIR / "api", wh.api_parquet, wh.api_pull_days)
        days = pull_window(coverage_end(wh), date.today())
        logger.info("pulling %s..%s (%d days)", days[0], days[-1], len(days))
        pull(days, RAW_DIR, RAW_DIR / "MANIFEST.json")
    build(RAW_DIR / "api", wh.api_parquet, wh.api_pull_days)


if __name__ == "__main__":
    main()
