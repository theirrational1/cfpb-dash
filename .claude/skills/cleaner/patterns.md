# CLEANER patterns: Polars and SQL/dbt

Polars for ingestion and notebooks; SQL/dbt (DuckDB) for staging, intermediate, marts. Polars code uses native expressions only (`.map_elements` is slow and opaque).

## Capture

```python
import hashlib, json, pathlib

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
# Append {url, retrieved_at, size, sha256} to data/raw/MANIFEST.json; test re-verifies.
# Re-ingest is a no-op when the recorded sha256 (and snapshot date) match.
```

```python
# Drift: name what changed, don't just say "header mismatch"
added   = [f for f in actual if f not in expected]
removed = [f for f in expected if f not in actual]
renamed = [(r, a) for r in removed for a in added if actual.index(a) == expected.index(r)]
# raise with all three (and "order changed" when the sets match but the order doesn't)

# Row counts: independent parser vs the engine (embedded newlines/quotes break naive counts)
with path.open(newline="") as f:
    n_records = sum(1 for _ in csv.reader(f)) - 1
```

## Limit + Edit

```python
import polars as pl
RENAMES = {"Date received": "date_received", "Company": "company"}  # full map, versioned
lf = pl.scan_csv(raw).select(list(RENAMES)).rename(RENAMES)
```

```sql
-- models/staging/stg_complaints.sql
select
    cast("Complaint ID" as bigint)  as complaint_id,
    cast("Date received" as date)   as date_received,
    trim("Company")                 as company,          -- Edit: trim keys
    "Timely response?" = 'Yes'      as timely            -- typed after a raw accepted_values test
from {{ source('raw', 'complaints') }}
```

```yaml
# Limit: the contract pins the exact columns and types; a stray or missing column fails
models:
  - name: stg_complaints
    config: {contract: {enforced: true}}
    columns:
      - {name: complaint_id, data_type: bigint, constraints: [{type: not_null}]}
      - {name: date_received, data_type: date}
```

## Audit

```python
lf.select(
    pl.all().null_count().name.suffix("_nulls"),
    pl.all().n_unique().name.suffix("_nunique"),
).collect()
lf.group_by(pl.col("date_received").dt.year(), "company_response").len().collect()
```

```yaml
# dbt tests. Raw values are tested on the source, before staging types them.
sources:
  - name: raw
    tables:
      - name: complaints
        columns:
          - name: '"Timely response?"'
            quote: false
            data_tests:
              - accepted_values: {arguments: {values: ['Yes', 'No']}}
models:
  - name: stg_complaints
    columns:
      - name: complaint_id
        data_tests: [unique, not_null]
      - name: state            # long / quoted value lists: a seed + relationships
        data_tests:
          - relationships: {arguments: {to: ref('us_state_codes'), field: state_code}}
```

```python
# Profile by period: label revisions and value regimes only show up per year
lf.group_by(pl.col("date_received").dt.year(), "product").len().sort("date_received").collect()
```

## Null

```sql
-- The same column means different things by row: encode with case, never a blanket coalesce
case
    when company_public_response is not null then company_public_response
    when date_received >= date '2015-01-01'             -- structural before the option existed
     and company_response <> 'In progress'              -- unknown while open (null stays null)
        then 'none_given'                               -- meaningful blank
end as company_public_response,
date_received >= date '2015-01-01' as public_response_available,   -- structural period flag
coalesce(tags like '%Older American%', false) as is_older_american  -- tag set -> booleans
```

```sql
-- tests/generic/null_count_at_most.sql: rare "error" nulls are capped, not forbidden
{% test null_count_at_most(model, column_name, max_nulls) %}
select count(*) from {{ model }} where {{ column_name }} is null
having count(*) > {{ max_nulls }}
{% endtest %}
-- yml: - null_count_at_most: {arguments: {max_nulls: "{{ var('issue_null_cap') }}"}}
```

```markdown
<!-- docs/decisions/nulls.md: one entry per nullable column -->
### company_public_response: structural before 2015; then meaningful blank or unknown
- Evidence: ... (counts by year and by status)
- Decision: ...
- Test: relationships to seed public_responses; null only pre-2015 / In progress / status missing
```

## Engineer

```python
# Map labels through an explicit table; never str.contains("relief") ("without relief" matches)
relief = pl.DataFrame({"company_response": [...], "is_relief": [...]})
lf.join(relief.lazy(), on="company_response", how="left").with_columns(
    (pl.col("date_sent_to_company") - pl.col("date_received")).dt.total_days().alias("forwarding_lag_days"),
)
```

```sql
select
    c.*,
    date_diff('day', c.date_received, c.date_sent_to_company) as forwarding_lag_days,
    m.is_relief                                               -- from seed company_responses
from {{ ref('stg_complaints') }} c
left join {{ ref('company_responses') }} m using (company_response)
-- test: every observed company_response appears in the seed
```

```yaml
# dbt unit test: hand-computed rows for each derived column
unit_tests:
  - name: forwarding_lag_keeps_minus_one
    model: int_complaints
    given:
      - input: ref('stg_complaints')
        rows:
          - {complaint_id: 1, date_received: 2024-01-02, date_sent_to_company: 2024-01-01}
    expect:
      rows:
        - {complaint_id: 1, forwarding_lag_days: -1}
```

## Restrict

```sql
-- marts: final grain = one row per complaint
select complaint_id, company_id, product_key, date_received, forwarding_lag_days, is_relief
from {{ ref('int_complaints') }}
where date_received <= {{ var('snapshot_date') }}
```

Reconciliation test: count(mart) = count(staging) − documented exclusions.
