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
    "Complaint ID"     as complaint_id,
    "Date received"    as date_received,
    "Company"          as company
from {{ source('raw', 'complaints') }}
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
# dbt schema tests
columns:
  - name: complaint_id
    tests: [unique, not_null]
  - name: timely
    tests:
      - accepted_values: {values: ['Yes', 'No']}
```

## Null

```sql
select
    coalesce(company_public_response, 'none_given') as company_public_response,  -- meaningful blank
    sub_issue                                        -- truly unknown: kept null, documented
from {{ ref('stg_complaints') }}
```

```markdown
<!-- docs/decisions/nulls.md -->
| column | null meaning | handling | test |
|---|---|---|---|
| company_public_response | company chose not to respond publicly | 'none_given' | not_null after staging |
```

## Engineer

```python
lf.with_columns(
    (pl.col("date_sent_to_company") - pl.col("date_received")).dt.total_days().alias("forwarding_lag_days"),
    pl.col("company_response").str.contains("relief").alias("is_relief"),
)
```

```sql
select
    *,
    date_diff('day', date_received, date_sent_to_company) as forwarding_lag_days,
    company_response like '%relief%'                      as is_relief
from {{ ref('stg_complaints') }}
```

## Restrict

```sql
-- marts: final grain = one row per complaint
select complaint_id, company_id, product_key, date_received, forwarding_lag_days, is_relief
from {{ ref('int_complaints') }}
where date_received <= {{ var('snapshot_date') }}
```

Reconciliation test: count(mart) = count(staging) − documented exclusions.
