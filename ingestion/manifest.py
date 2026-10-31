"""Raw landing manifest (data/raw/MANIFEST.json): load, verify checksums, append entries.

Entry paths are relative to the manifest's directory.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ("path", "source", "source_url", "retrieved_at", "size_bytes", "sha256")
CHUNK_SIZE = 1 << 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate(manifest: dict[str, Any], source: Path) -> None:
    seen: set[str] = set()
    for i, entry in enumerate(manifest["files"]):
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        if missing:
            raise ValueError(f"{source}: files[{i}] missing keys {missing}")
        if entry["path"] in seen:
            raise ValueError(f"{source}: duplicate path {entry['path']!r}")
        seen.add(entry["path"])


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    _validate(manifest, manifest_path)
    return manifest


def verify_manifest(manifest_path: Path) -> list[str]:
    """Recompute size and sha256 for every entry. Returns problems; empty means all match."""
    manifest = load_manifest(manifest_path)
    root = manifest_path.parent
    problems: list[str] = []
    for entry in manifest["files"]:
        rel = entry["path"]
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
            continue
        size = path.stat().st_size
        if size != entry["size_bytes"]:
            problems.append(f"size mismatch: {rel} expected {entry['size_bytes']} got {size}")
        logger.info("hashing %s (%d bytes)", rel, size)
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            problems.append(f"sha256 mismatch: {rel} expected {entry['sha256']} got {digest}")
    for p in problems:
        logger.error(p)
    logger.info("verified %d files, %d problems", len(manifest["files"]), len(problems))
    return problems


def append_entry(
    manifest_path: Path,
    entry: dict[str, Any],
    generated_at: str,
    notes: str | None = None,
) -> None:
    """Add one file entry, keeping the existing format (indent=2, trailing newline)."""
    manifest = load_manifest(manifest_path)
    manifest["files"].append(entry)
    _validate(manifest, manifest_path)
    manifest["generated_at"] = generated_at
    if notes is not None:
        manifest["notes"] = notes
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    logger.info("added %s to %s", entry["path"], manifest_path)
