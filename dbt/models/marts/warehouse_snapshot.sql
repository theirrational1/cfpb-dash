-- Provenance stamp: the raw snapshot this warehouse was built from, frozen at build time.
-- query_metric reads provenance from here, so labels always match the data queried.
-- It refs the fact table and the spine so a failed build skips it and keeps the old stamp;
-- read_snapshot_stamp then refuses to serve if staging or the fact moved without it.
-- depends_on: {{ ref('metricflow_time_spine') }}
select
    cast(snapshot_date as varchar) as snapshot_date,
    cast(source_sha256 as varchar) as source_sha256,
    cast(source_path as varchar) as source_path,
    cast("rows" as bigint) as source_rows,
    cast(built_at as varchar) as ingested_at,
    fct.fact_rows,
    cast(fct.data_start as varchar) as data_start,
    cast(fct.data_end as varchar) as data_end,
    current_timestamp as built_at
from read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true)
cross join (
    select count(*) as fact_rows, min(date_received) as data_start, max(date_received) as data_end
    from {{ ref('fct_complaints') }}
) as fct
