"""Result cache: one JSON file per key (sha256 of model, prompt version, input)."""

import json
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        return json.loads(path.read_text()) if path.is_file() else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        tmp = self.root / f"{key}.json.tmp"
        tmp.write_text(json.dumps(value, sort_keys=True))
        tmp.replace(self.root / f"{key}.json")
