"""Download the CFPB bulk complaint file into data/raw/bulk/ and record it in MANIFEST.json.

Run: uv run python -m ingestion.fetch_bulk
"""

import hashlib
import logging
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import urlopen

from core.log import configure_logging
from ingestion.manifest import CHUNK_SIZE, append_entry

logger = logging.getLogger(__name__)

BULK_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
SOURCE = "CFPB Consumer Complaint Database — bulk download (CSV)"
RAW_DIR = Path("data/raw")
NOTES = (
    "Narrative files: retrieved_at taken from file modification time. "
    "Bulk file: retrieved_at is the download date (ingestion.fetch_bulk)."
)
PROGRESS_EVERY = 50 * (1 << 20)


def fetch_bulk(url: str, raw_dir: Path, retrieved_at: date) -> Path:
    """Stream `url` to raw_dir/bulk/complaints_<date>.csv.zip, then append a manifest entry.

    Raw files are immutable: refuses to overwrite. On a short read or a non-zip body the
    `.part` file is left in place for inspection and an error is raised.
    """
    dest = raw_dir / "bulk" / f"complaints_{retrieved_at.isoformat()}.csv.zip"
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; raw files are immutable")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    h = hashlib.sha256()
    written = 0
    next_log = PROGRESS_EVERY
    with urlopen(url) as resp:
        expected = int(resp.headers["Content-Length"])
        logger.info("downloading %s (%d bytes) -> %s", url, expected, part)
        with part.open("wb") as out:
            while chunk := resp.read(CHUNK_SIZE):
                out.write(chunk)
                h.update(chunk)
                written += len(chunk)
                if written >= next_log:
                    logger.info("%d / %d bytes", written, expected)
                    next_log += PROGRESS_EVERY

    if written != expected:
        raise OSError(f"short download: got {written} of {expected} bytes; see {part}")
    if not zipfile.is_zipfile(part):
        raise ValueError(f"downloaded body is not a zip file; see {part}")
    part.rename(dest)

    append_entry(
        raw_dir / "MANIFEST.json",
        {
            "path": dest.relative_to(raw_dir).as_posix(),
            "source": SOURCE,
            "source_url": url,
            "retrieved_at": retrieved_at.isoformat(),
            "size_bytes": written,
            "sha256": h.hexdigest(),
        },
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        notes=NOTES,
    )
    logger.info("saved %s sha256=%s", dest, h.hexdigest())
    return dest


def main() -> None:
    configure_logging()
    fetch_bulk(BULK_URL, RAW_DIR, date.today())


if __name__ == "__main__":
    main()
