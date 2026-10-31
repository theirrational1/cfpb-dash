# AGENTS.md

## Prime directive

**Do not work if you have any questions or something is not clear. Ask for clarification.**
When running unattended (batch jobs, scheduled runs), write the question to `QUESTIONS.md` and stop instead of guessing.

Instructions for coding agents in this repo. Product detail lives in `PRD.md`; work items in `TASKS.md`.

## Project

CFPB Complaint Intelligence: ingestion → DuckDB + dbt → MetricFlow semantic layer → Streamlit dashboard → agent that answers only through governed metrics → eval suite. Read `PRD.md` before starting any milestone.

## Python toolchain

- Use **uv**. Run Python and tools with `uv run` (e.g. `uv run python`, `uv run pytest`).
- **Do not edit `pyproject.toml` dependencies directly.** Use `uv add LIB` or `uv add --dev LIB`, and ask before adding any dependency.
- **pytest** for TDD. Shared fixtures (e.g. the small CFPB fixture dataset) go in `conftest.py`; don't repeat setup across tests.
- **Ruff** to lint and format. **Ty** to typecheck. **prek** for pre-commit hooks. (Fallbacks if a tool causes friction: mypy, pre-commit — ask first.)
- **Use logging** (stdlib `logging`, structured where useful) so failures are debuggable by an AI from the logs alone.
- **Do not hide or wrap errors.** No bare `except`, no catch-and-continue, no swallowing exceptions into `None`. Let errors surface with context.
- Polars, where used: native expressions only; **no `.map_elements`** for math or per-row Python.

## Commands (target; update as they become real)

```bash
uv sync
uv run python -m ingestion.fetch_bulk     # download CFPB bulk zip → data/raw/bulk/ + MANIFEST.json
uv run pytest -m data                     # recompute every checksum in data/raw/MANIFEST.json (slow, local only)
uv run python -m ingestion.bulk           # backfill from CFPB bulk file
uv run python -m ingestion.incremental    # daily API pull
uv run dbt build --project-dir dbt        # models + tests
uv run mf validate-configs
uv run mf query --metrics <m> --group-by <d>
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run python -m evals.run --suite e1 --split dev --model qwen
uv run streamlit run app/main.py
```

## Repo layout (target)

```
ingestion/        bulk.py, incremental.py, schema_check.py
dbt/              models/{staging,intermediate,marts}, semantic_models/, tests/
agent/            adapters/, tools/, guardrails.py, provenance.py
narratives/       taxonomy/ (versioned), dedupe.py, extract.py
evals/            harness/, datasets/{dev,heldout}/ (LOCKED), results/ (gitignored)
app/              Streamlit
notebooks/        profiling only
docs/decisions/   cleaning and design decisions
tests/            conftest.py + tests
data/             gitignored: raw/, snapshots/, duckdb file
```

## Working rules

1. Work **one task at a time** from `TASKS.md`, by ID. Tick it off when done. Don't start the next milestone until the current one's "Done when" passes.
2. **Tests first (TDD)** for deterministic code: ingestion, transforms, metrics, tools, guardrails, scoring.
3. **Small diffs.** If a change exceeds ~300 lines, stop and propose a split.
4. **Ask before** changing a metric definition, the taxonomy, a public tool signature, or adding a dependency.

## Data cleaning: CLEANER

- Before any ingestion, profiling, or dbt staging/intermediate/mart work, load the `cleaner` skill.
- Every null decision is recorded in `docs/decisions/nulls.md` and enforced by a test before the model ships.

## Data rules

- **Never commit data** (raw files, DuckDB, narratives, results). `data/` is gitignored.
- **Never commit `PRD.md`.** It is local only (gitignored); read and update it, but don't stage it.
- Raw landing files are immutable; record checksums in `data/raw/MANIFEST.json`.
- Evals run against a **frozen snapshot**, never live data.
- Ingestion **fails loudly** on schema drift; never silently drop or rename fields.

## Metrics and governance rules

- Metrics are defined **only** in MetricFlow YAML. No metric math in Python, Streamlit, or prompts.
- The agent gets numbers **only** via `query_metric`. No free-form SQL tool in the MVP.
- Taxonomy files are versioned (`narratives/taxonomy/v1.yaml`). Never edit a released version.
- Every agent answer carries provenance (metrics, filters, time range, snapshot date) and coverage caveats where relevant.
- The agent never concludes that a company broke the law.

## LLM rules

- All model calls go through `agent/adapters/` (Anthropic, Ollama). No direct SDK calls elsewhere.
- Log every call's token usage and cost to the usage table.
- Cache results by (model, prompt version, input hash).
- Respect the harness budget cap. Iterate with local Qwen; use paid models for scored runs.
- Prompts live in versioned files, not inline strings.

## Eval rules

- **Do not edit** `evals/datasets/` or scoring code to make a result pass. If a case looks wrong, report it and stop.
- Held-out split only at milestone checkpoints.
- Report scores with model, prompt version, snapshot, and cost.

## Definition of done (any task)

Tests pass, `dbt build` passes, ruff and ty clean, task ticked in `TASKS.md`, and any design decision added to `PRD.md`'s decision log.
