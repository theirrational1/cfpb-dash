---
name: cleaner
description: CLEANER method for cleaning tabular data (Capture, Limit, Edit, Audit, Null, Engineer, Restrict), tool-agnostic with Polars and SQL/dbt patterns. Use when ingesting, profiling, or cleaning a new table or file, writing dbt staging/intermediate/mart models, or deciding how to handle missing values.
---

# CLEANER (v1)

> v1: revised from M0 profiling and M2 staging of an 18.8M-row public complaints dataset (v0 was drafted from talk slides before touching data).

Seven stages, in order. Based on Matt Harrison's CLEANER methodology (*Effective Pandas* / *Effective Polars*, 3rd editions). Tool agnostic: each stage has Polars and SQL/dbt patterns in [`patterns.md`](patterns.md).

Every stage leaves an **artifact**: a test, a recorded decision, or a model. A stage with no artifact is not done.

## Where each stage lives

| Stage | Layer | Artifact |
|---|---|---|
| Capture | raw landing | immutable file + manifest entry (source, retrieved date, size, sha256); drift check; row-count reconciliation |
| Limit | staging | explicit column list enforced by a model contract; dropped columns listed in the decision log |
| Edit | staging | snake_case names; rename map; trimmed keys |
| Audit | profiling + tests | profile notes by period; tests for types, ranges, accepted values, uniqueness |
| Null | staging | one entry per nullable column in `docs/decisions/nulls.md`; a test enforcing it |
| Engineer | intermediate | derived columns, each with a unit test on hand-computed rows; mappings in seeds |
| Restrict | marts | final grain and columns, documented; row-count reconciliation test |

## Stages

1. **Capture.** Land the source untouched; downstream work reads copies.
   - Read every column as text first, typing comes later.
   - Reconcile the row count with an independent parser (e.g. stdlib `csv` vs the engine), because embedded newlines and quotes break naive counts.
   - Fail on schema drift, and name what changed (added, removed, likely renamed, reordered). Never silently drop or rename a field.
   - Make re-ingestion idempotent, keyed on the source checksum.
   - Done when the file is in `data/raw/`, listed in the manifest, its checksum verifies, and both counts agree.

2. **Limit.** Select only the columns some metric, dimension, filter, or test needs, and **enforce the list with a model contract** (exact columns and types), so a stray column fails the build. Done when every kept column has a named consumer.

3. **Edit.** Make names valid Python identifiers: lowercase snake_case, no spaces or punctuation. Trim whitespace in join and grouping keys (names, codes). Done when the rename map covers every column, names are unique, and keys are trimmed.

4. **Audit.** For every kept column: type, range, cardinality, and distinct values, **profiled by period** when the source spans years.
   - Category lists get revised, value regimes change and fields appear. All of this only shows up when you look by year.
   - Test raw values (accepted values) **before** typing them; for example, test `Yes`/`No` before casting to boolean.
   - Record surprises as profile notes.
   - Done when every column has a type and a test encoding its expected domain.

5. **Null.** For every column with nulls, decide what a null *means* before deciding what to do with it. The same column can mean different things by row, depending on period or status, so encode it with a `case`, never a blanket `coalesce`:
   - **meaningful blank** → encode as an explicit value (`'none_given'`), or as booleans when the column holds a set of tags;
   - **truly unknown** → keep null; metrics must state how they treat it;
   - **structural** (the field didn't exist yet or didn't apply) → keep null and add a period flag column;
   - **error** (a handful of rows) → keep the rows for counts and exclude them from the affected metrics with a counted reason. Test with a **count cap** (`null_count_at_most`, the cap held in a variable), not `not_null`, so growth fails the build.

   Done when every nullable column has a recorded decision and a test enforcing it. Silent default-fills fail this stage.

6. **Engineer.** Create analysis columns: durations, flags, mapped categories, keys.
   - Map labels with an explicit **seed table**, never string matching (`like '%relief%'` also matches "without relief").
   - Keep mappings that span category revisions in versioned seeds, with tests that every observed label maps.
   - Use native vectorised expressions.
   - Done when each derived column has a unit test with hand-computed rows.

7. **Restrict.** Choose output rows and columns for the consumer: the grain, the filters, the final column set. Aggregate here, after preparation. Done when the grain is documented and a reconciliation test ties row counts back to staging.

## Rules across stages

- Audit before Null and Engineer: decisions follow evidence from the data, not assumptions.
- Each stage is its own model or step, so a failure points at one stage.
- Log counts entering and leaving each stage; a row-count change is always explained.
- Errors surface; a failed check stops the pipeline with context.
- **Test on real rows of every pattern.** Keep a small fixture sampled from the real data by period and by null or odd-value pattern, rather than hand-made rows alone.
- Long value lists with quotes or punctuation belong in a seed, tested with `relationships`, not inline in `accepted_values`.
