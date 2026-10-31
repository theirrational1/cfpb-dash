"""Ask the agent one question against local Qwen (manual check; not used by tests or CI).

Run: uv run python -m agent.ask "How many complaints did CITIBANK, N.A. receive in March 2026?"
"""

import argparse
import uuid
from dataclasses import asdict
from pathlib import Path

from agent.adapters.cache import JsonCache
from agent.adapters.gateway import Budget, Gateway
from agent.adapters.ollama import DEFAULT_MODEL, OllamaAdapter
from agent.adapters.usage import UsageLog
from agent.loop import run
from core.log import configure_logging
from core.warehouse import REPO_ROOT, Warehouse

USAGE_DB = REPO_ROOT / "data" / "ops" / "usage.duckdb"
CACHE_DIR = REPO_ROOT / "data" / "cache"


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--warehouse", type=Path, help="warehouse root (default data/warehouse)")
    parser.add_argument("--budget-usd", type=float, default=0.10)
    args = parser.parse_args()

    gateway = Gateway(
        OllamaAdapter(args.model),
        UsageLog(USAGE_DB),
        JsonCache(CACHE_DIR),
        f"ask-{uuid.uuid4()}",
        budget=Budget(cap_usd=args.budget_usd),
    )
    wh = Warehouse(args.warehouse) if args.warehouse else Warehouse()
    answer = run(args.question, gateway, wh)
    print(answer.answer)
    print(f"value={answer.value} traced={answer.value_traced} steps={answer.steps}")
    for p in answer.provenance:
        print("provenance:", asdict(p))


if __name__ == "__main__":
    main()
