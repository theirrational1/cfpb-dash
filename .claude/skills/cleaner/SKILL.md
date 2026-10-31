---
name: cleaner
description: CLEANER method for cleaning tabular data (Capture, Limit, Edit, Audit, Null, Engineer, Restrict), tool-agnostic with Polars and SQL/dbt patterns. Use when ingesting, profiling, or cleaning a new table or file, writing dbt staging/intermediate/mart models, or deciding how to handle missing values.
---

# CLEANER (v0)

> v0: drafted from talk slides before touching real data. Revise after M0 profiling and M2 staging (TASKS M2-11).

Seven stages, in order. Based on Matt Harrison's CLEANER methodology (*Effective Pandas* / *Effective Polars*, 3rd editions). Tool agnostic: each stage has Polars and SQL/dbt patterns in [`patterns.md`](patterns.md).

Every stage leaves an **artifact**: a test, a recorded decision, or a model. A stage with no artifact is not done.

## Where each stage lives

| Stage | Layer | Artifact |
|---|---|---|
| Capture | raw landing | immutable file + manifest entry (source, retrieved date, size, sha256) |
| Limit | staging | explicit column list; dropped columns listed in the decision log |
| Edit | staging | snake_case names; rename map |
| Audit | profiling + tests | profile notes; dbt tests for types, ranges, accepted values, uniqueness |
| Null | staging | one entry per nullable column in `docs/decisions/nulls.md`; a test enforcing it |
| Engineer | intermediate | derived columns, each with a test against a hand-computed case |
| Restrict | marts | final grain and columns, documented; row-count reconciliation test |

## Stages

1. **Capture.** Land the source untouched. Downstream work reads copies, never the original. Done when the file is in `data/raw/`, listed in the manifest, and its checksum verifies.

2. **Limit.** Select only the columns some metric, dimension, filter, or test needs. Done when every kept column has a named consumer.

3. **Edit.** Make names valid Python identifiers: lowercase snake_case, no spaces or punctuation. Done when the rename map covers every column and names are unique.

4. **Audit.** For every kept column: type, range (min/max, date bounds), cardinality, and distinct values for low-cardinality columns, tracked over time where the source spans years. Record surprises as profile notes. Done when every column has a type and a test encoding its expected domain.

5. **Null.** For every column with nulls, decide what a null *means* before deciding what to do with it:
   - **meaningful blank** → encode as an explicit value (e.g. `'none_given'`), never treat as missing;
   - **truly unknown** → keep null; metrics must state how they treat it;
   - **structural** (field didn't exist yet, e.g. before a form change) → keep null, flag the period;
   - **error** → fix at source mapping or exclude with a counted reason.
   Done when every nullable column has a recorded decision and a test enforcing it. Silent default-fills fail this stage.

6. **Engineer.** Create analysis columns: durations, flags, mapped categories, keys. Use native vectorised expressions. Done when each derived column has a test with a hand-computed example.

7. **Restrict.** Choose output rows and columns for the consumer: the grain, the filters, the final column set. Aggregate here, after preparation. Done when the grain is documented and a reconciliation test ties row counts back to staging.

## Rules across stages

- Audit before Null and Engineer: decisions follow evidence from the data, not assumptions.
- Each stage is its own model or step, so a failure points at one stage.
- Log counts entering and leaving each stage; a row-count change is always explained.
- Errors surface; a failed check stops the pipeline with context.
