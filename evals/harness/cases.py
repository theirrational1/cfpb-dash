"""Eval cases are TOML files: [[cases]] with id, question, ground_truth_sql."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    ground_truth_sql: str


def load_cases(path: Path) -> list[Case]:
    raw = tomllib.loads(path.read_text())["cases"]
    cases = [Case(c["id"], c["question"], c["ground_truth_sql"]) for c in raw]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case ids {ids}")
    return cases
