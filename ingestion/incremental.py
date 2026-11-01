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

import csv
import io
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from ingestion.manifest import append_entry, sha256_file
from ingestion.raw_csv import BULK_COLUMNS
from ingestion.schema_check import check_fields

logger = logging.getLogger(__name__)

API_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
SOURCE = "CFPB Consumer Complaint Database — Search API (CSV export, one day per file)"
LOOKBACK_DAYS = 15
RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 4
REQUEST_PAUSE_S = 0.5  # be polite: requests are sequential with a short pause

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
            wait = 2**attempt
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
