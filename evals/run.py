"""Run an eval suite. Report scores with model, prompt version, snapshot and cost.

Run: uv run python -m evals.run --suite e1 --split dev --model qwen
"""

import argparse
from pathlib import Path

from agent.adapters.ollama import DEFAULT_MODEL, OllamaAdapter
from core.log import configure_logging
from core.warehouse import REPO_ROOT
from evals.harness.cases import load_cases
from evals.harness.runner import run_suite
from ingestion.snapshot import resolve_eval_warehouse

DATASETS = REPO_ROOT / "evals" / "datasets"
MODELS = {"qwen": DEFAULT_MODEL}


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--split", required=True, choices=["dev", "heldout"])
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--budget-usd", type=float, default=1.0)
    parser.add_argument(
        "--warehouse", type=Path, help="frozen snapshot dir (default: newest in data/snapshots)"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="always call the model (scored runs)"
    )
    args = parser.parse_args()

    summary = run_suite(
        load_cases(DATASETS / args.split / f"{args.suite}.toml"),
        OllamaAdapter(MODELS[args.model]),
        resolve_eval_warehouse(args.warehouse),  # frozen snapshots only (AGENTS.md)
        suite=args.suite,
        split=args.split,
        results_dir=REPO_ROOT / "evals" / "results",
        ops_dir=REPO_ROOT / "data" / "ops",
        budget_usd=args.budget_usd,
        use_cache=not args.no_cache,
    )
    print(
        f"{summary['suite']}/{summary['split']} model={summary['model']} "
        f"prompt={summary['prompt_version']} snapshot={summary['snapshot_date']}: "
        f"{summary['passed']}/{summary['n']} passed, cost ${summary['cost_usd']:.4f}, "
        f"cache hits {summary['cache_hits']}"
    )


if __name__ == "__main__":
    main()
