"""Usage table: one row per model call (tokens, cost, cache hit) in a DuckDB file."""

from pathlib import Path

import duckdb

from agent.adapters.base import Usage

DDL = """CREATE TABLE IF NOT EXISTS usage (
    ts TIMESTAMPTZ, run_id VARCHAR, model VARCHAR, prompt_version VARCHAR,
    input_tokens BIGINT, output_tokens BIGINT, cost_usd DOUBLE, cache_hit BOOLEAN)"""


class UsageLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path)) as con:
            con.execute(DDL)

    def record(
        self,
        run_id: str,
        model: str,
        prompt_version: str,
        usage: Usage,
        cost_usd: float,
        cache_hit: bool,
    ) -> None:
        with duckdb.connect(str(self.path)) as con:
            con.execute(
                "INSERT INTO usage VALUES (now(), ?, ?, ?, ?, ?, ?, ?)",
                [run_id, model, prompt_version, usage.input_tokens, usage.output_tokens,
                 cost_usd, cache_hit],
            )  # fmt: skip
