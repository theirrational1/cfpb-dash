-- Fails if the raw parquet and snapshot.json disagree (e.g. a half-finished re-ingest).
select n_staging, source_rows
from (select count(*) as n_staging from {{ ref('stg_complaints') }})
cross join {{ ref('warehouse_snapshot') }}
where n_staging != source_rows
