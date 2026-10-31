# TASKS.md

Small, specific tasks to implement `PRD.md`. TDD for every feature. One milestone at a time; a milestone is done only when its **Done when** checks pass.

**Conventions**
- Every task has a unique ID (`M2-04`). Reference tasks by ID in commits and messages.
- `[ ]` todo · `[x]` done · **(you)** = needs Saksham, not an agent.
- **Tracks:** within a milestone, tracks (A, B, …) can run in parallel; tasks inside a track run in order. Default to one agent at a time (Pro limits); tracks mark what *could* run in parallel.

---

## M0 — Setup, data capture, profiling

**Done when:** raw data captured with checksums; profiling selects the narrative product by the rule; repo, AGENTS.md, CI skeleton exist.

**Track A — capture (do first)**
- [x] M0-01 **(you) URGENT:** download all 21 narrative archive files from the CFPB FOIA Reading Room → `data/raw/narratives/`
- [x] M0-02 Download CFPB bulk file → `data/raw/`
- [x] M0-03 Write `data/raw/MANIFEST.json` (url, retrieved date, size, sha256 per file) + test that verifies checksums *(manifest written for the 21 narrative files; add bulk file after M0-02; test still todo)*

**Track B — repo**
- [x] M0-04 Create public repo; `uv init`; dev deps via `uv add --dev` (pytest, ruff, ty, prek)
- [x] M0-05 `.gitignore` (data/, results/, *.duckdb; but keep `!data/raw/MANIFEST.json` tracked), `PRD.md`, `AGENTS.md`, `CLAUDE.md`, `TASKS.md`, `docs/decisions/`
- [x] M0-06 prek hooks (ruff, ty) + CI (GitHub Actions: ruff, ty, pytest)
- [x] M0-07 Logging config module used by all entry points

**Track C — profiling (after Track A), CLEANER Audit pass**
- [x] M0-08 Row counts by year, product, company; null rates per field; types and cardinality
- [x] M0-09 Distinct `company_response` values over time
- [x] M0-10 Product/issue label changes over time (input to mapping layer)
- [x] M0-11 Narrative counts by product and company; duplicate/template rate estimate
- [x] M0-12 Apply product rule (≥20K narratives, ≥15 companies above threshold, no issue >50%, bank-analyst relevant; default credit cards); record in PRD decision log
- [x] M0-13 Draft minimum-volume threshold (versioned parameter)
- [x] M0-14 First draft of `docs/decisions/nulls.md` from profiling
- [x] M0-15 Narrative coverage by month (share of complaints with a narrative) → set the reliable cutoff month; record in PRD
- [x] M0-16 Archive vs bulk: overlap by `complaint_id`, records only in one, structured-field mismatches (expected for recent complaints)

## M1 — Walking skeleton (thin vertical slice)

**Done when:** one metric for one company flows end to end — ingestion → dbt → MetricFlow → Streamlit chart → one agent tool → one passing eval case — with tests at each step. Ugly is fine.

- [x] M1-01 Fixture dataset (~1K rows, one product) in `tests/fixtures/` + `conftest.py` fixture
- [x] M1-02 Minimal ingestion: fixture/bulk slice → raw parquet
- [x] M1-03 Minimal dbt: one staging model + one fact model + 2 tests
- [x] M1-04 One MetricFlow metric (`complaint_count` by month) + test vs hand-written SQL
- [x] M1-05 Streamlit page: company picker + one chart from the metric
- [x] M1-06 Model adapter (Ollama/Qwen) + `query_metric` tool wrapping MetricFlow
- [ ] M1-07 Minimal agent loop answering one question with provenance
- [ ] M1-08 Eval harness skeleton: one E1 case, deterministic scorer, usage/cost log, cache, budget cap
- [ ] M1-09 CI runs the skeleton on the fixture (no paid model calls)

## M2 — Data layer

**Done when:** full dbt build passes with tests; drift check fails loudly on a changed field; frozen eval snapshot exists.

**Track A — ingestion**
- [ ] M2-01 `schema_check.py` + tests (fail on added/removed/renamed fields)
- [ ] M2-02 Full bulk ingestion, idempotent
- [ ] M2-03 Incremental API pull by `date_received`, upsert by `complaint_id`, changed-record handling; tests with recorded API fixtures

**Track B — dbt (CLEANER: Limit, Edit, Audit, Null → staging; Engineer → intermediate)**
- [ ] M2-04 Staging: limit columns, snake_case names, types
- [ ] M2-05 Null handling per `docs/decisions/nulls.md`, with tests
- [ ] M2-11 **(you + agent)** Revise `cleaner` skill v0 → v1 from what M0 profiling and M2-04/05 taught; only then copy it to user-level skills
- [ ] M2-06 Category mapping across years (seed table) + tests
- [ ] M2-07 Company dimension + name resolution; match-rate test
- [ ] M2-08 Intermediate: forwarding lag, relief flag, month keys
- [ ] M2-09 Complaint fact; tests: unique id, not-null, accepted values, row count vs raw

**Then**
- [ ] M2-10 Snapshot job: freeze a dated DuckDB copy for evals

## M3 — Metrics

**Done when:** every metric and peer-group model matches hand-written SQL in tests.

- [ ] M3-01 Remaining metrics from PRD §7 (confirm definitions against M0 profiling)
- [ ] M3-02 Reference SQL + tests comparing to `mf query`
- [ ] M3-03 Peer groups: product-based, min threshold, complaint-volume tiers (labelled as such)
- [ ] M3-04 Coverage source table (freshness, exclusions, narrative cutoff)

## M4 — Dashboard

**Done when:** scorecard and peer view (with toggle) work for any company; no-LLM baseline recorded.

- [ ] M4-01 Company search (uses resolution)
- [ ] M4-02 Scorecard tab
- [ ] M4-03 Peer tab with All / Similar-volume-tier toggle; shows basis, threshold, rank
- [ ] M4-04 Coverage panel
- [ ] M4-05 **(you)** Record which E1 questions the dashboard alone answers (baseline)

## M5 — Agent

**Done when:** all tools implemented and tested; provenance logged; guardrails active; E1 and E3 dev scores recorded with cost.

**Track A — tools**
- [ ] M5-01 Anthropic adapter (API key + subscription for dev); mocked-client tests
- [ ] M5-02 Remaining tools from PRD §6, each with unit tests
- [ ] M5-03 Output contract + provenance logging → dbt model
- [ ] M5-04 Guardrails (wrongdoing, coverage caveats, predictions) + tests

**Track B — eval sets (you)**
- [ ] M5-05 **(you)** Write E1 (~40 questions) and E3 (~15) with dev/held-out split; ground truth via SQL

**Then**
- [ ] M5-06 Run E1 + E3 on dev (Qwen first, then Haiku); record baseline; set thresholds
- [ ] M5-07 Chat panel in Streamlit

## M6 — Narratives

**Done when:** taxonomy v1 frozen; 200 gold labels verified; extraction complete; E2 scored for Haiku, Qwen, Jev; deep-dive tab live.

- [ ] M6-01 Template/duplicate detection on narratives; flag column + rate report
- [ ] M6-02 Sample ~500 originals; LLM proposes categories
- [ ] M6-03 **(you)** Curate to ~15 + "other"; freeze `taxonomy/v1.yaml`
- [ ] M6-04 Pre-label 200 gold narratives (originals + labelled share of templates)
- [ ] M6-05 **(you)** Verify every gold label
- [ ] M6-06 Extraction pipeline: structured output, batch, cache, cost log; estimate with `count_tokens` first
- [ ] M6-07 E2: Haiku vs Qwen vs Jev (accuracy, macro-F1, calibration, cost); agreement with consumer labels
- [ ] M6-08 Full extraction run on the chosen slice
- [ ] M6-09 Issue deep-dive tab + `get_issue_breakdown` tool

## M7 — Report (timeboxed: one weekend)

**Done when:** E4 run; held-out scores recorded; README with headline numbers and cost; screen recording.

- [ ] M7-01 E4: read-only SQL agent with markdown metric docs; rerun E1; compare
- [ ] M7-02 Held-out runs for E1–E4
- [ ] M7-03 README: problem, architecture diagram, decisions, headline numbers, cost, limitations
- [ ] M7-04 **(you)** 2-minute screen recording

## M8 — Stretch (only after M7 ships)

- [ ] M8-01 Governed memory (watchlists, saved peer groups, notes; agent proposes, analyst approves)
- [ ] M8-02 FDIC size tiers for banks (entity resolution + match-rate test)
- [ ] M8-03 Second narrative product (taxonomy v1 for it)
- [ ] M8-04 Distillation: LoRA-tune Qwen on Haiku labels (MLX), score on gold
- [ ] M8-05 Logged read-only SQL escape hatch, only if E1 shows questions the metric tools can't answer
