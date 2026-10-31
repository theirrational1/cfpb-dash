"""Run a suite: one agent answer per case, scored against SQL ground truth on the snapshot.

Each case result is appended to results/<run_id>.jsonl as soon as it is scored, so a run
stopped by the budget cap keeps what it finished. Agent failures (no governed tool call, bad
JSON, bad tool arguments, step limit) are scored as `error` with the exception recorded;
BudgetExceeded is never caught.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from agent.adapters.base import ChatAdapter
from agent.adapters.cache import JsonCache
from agent.adapters.gateway import Budget, BudgetExceeded, Gateway
from agent.adapters.usage import UsageLog
from agent.loop import PROMPT_VERSION, NoGovernedNumbersError, run
from core.warehouse import Warehouse
from evals.harness.cases import Case
from evals.harness.scoring import score

logger = logging.getLogger(__name__)

AGENT_FAILURES = (
    NoGovernedNumbersError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
    RuntimeError,
)


def ground_truth(case: Case, warehouse: Warehouse) -> int | float:
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    rows = con.execute(case.ground_truth_sql).fetchall()
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError(f"{case.id}: ground truth SQL must return one value, got {rows}")
    return rows[0][0]


def _usage_totals(usage: UsageLog, run_id: str) -> tuple[int, int, float]:
    with duckdb.connect(str(usage.path), read_only=True) as con:
        row = con.execute(
            """SELECT coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0),
                      coalesce(sum(cost_usd), 0) FROM usage WHERE run_id = ?""",
            [run_id],
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), float(row[2])


def run_suite(
    cases: list[Case],
    adapter: ChatAdapter,
    warehouse: Warehouse,
    suite: str,
    split: str,
    results_dir: Path,
    ops_dir: Path,
    budget_usd: float,
) -> dict[str, Any]:
    run_id = f"{suite}-{split}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    snapshot = json.loads(warehouse.snapshot_json.read_text())
    usage = UsageLog(ops_dir / "usage.duckdb")
    cache = JsonCache(ops_dir / "cache")
    budget = Budget(cap_usd=budget_usd)
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{run_id}.jsonl"
    meta = {
        "run_id": run_id,
        "suite": suite,
        "split": split,
        "model": adapter.model,
        "prompt_version": PROMPT_VERSION,
        "snapshot_date": snapshot["snapshot_date"],
        "source_sha256": snapshot["source_sha256"],
    }

    records: list[dict[str, Any]] = []
    for case in cases:
        case_run = f"{run_id}:{case.id}"
        gateway = Gateway(adapter, usage, cache, run_id=case_run, budget=budget)
        expected = ground_truth(case, warehouse)
        record: dict[str, Any] = {**meta, "kind": "case", "case_id": case.id, "expected": expected}
        try:
            answer = run(case.question, gateway, warehouse)
        except BudgetExceeded:
            raise
        except AGENT_FAILURES as e:
            logger.exception("case %s: agent failed", case.id)
            record |= {"status": "error", "error": f"{type(e).__name__}: {e}", "value": None}
        else:
            record |= {
                "status": score(answer.value, expected),
                "value": answer.value,
                "value_traced": answer.value_traced,
                "answer": answer.answer,
                "steps": answer.steps,
            }
        tin, tout, cost = _usage_totals(usage, case_run)
        record |= {"input_tokens": tin, "output_tokens": tout, "cost_usd": cost}
        records.append(record)
        with out.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        logger.info("case %s: %s (expected %s, got %s)", case.id, record["status"], expected,
                    record["value"])  # fmt: skip

    passed = sum(r["status"] == "pass" for r in records)
    summary = {
        **meta,
        "kind": "summary",
        "n": len(records),
        "passed": passed,
        "accuracy": passed / len(records) if records else 0.0,
        "cost_usd": sum(r["cost_usd"] for r in records),
        "cases": records,
    }
    with out.open("a") as f:
        f.write(json.dumps({k: v for k, v in summary.items() if k != "cases"}) + "\n")
    logger.info("run %s: %d/%d passed, cost $%.4f", run_id, passed, len(records),
                summary["cost_usd"])  # fmt: skip
    return summary
