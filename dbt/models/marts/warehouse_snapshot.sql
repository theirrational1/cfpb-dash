-- Provenance stamp: the raw snapshot this warehouse was built from, frozen at build time.
-- query_metric reads provenance from here, so labels always match the data queried.
-- It refs the fact table and the spine so a failed build skips it and keeps the old stamp;
-- read_snapshot_stamp then refuses to serve if staging or the fact moved without it.
-- snapshot_date: the bulk snapshot date, or the latest API pull's UTC date if later.
-- depends_on: {{ ref('metricflow_time_spine') }}
select
    cast(greatest(
        cast(s.snapshot_date as date), coalesce(cast(timezone('UTC', api.latest_pulled_at) as date), date '0001-01-01')
    ) as varchar) as snapshot_date,
    cast(s.snapshot_date as varchar) as bulk_snapshot_date,
    cast(s.source_sha256 as varchar) as source_sha256,
    cast(s.source_path as varchar) as source_path,
    cast(s."rows" as bigint) as source_rows,
    cast(s.built_at as varchar) as ingested_at,
    api.api_pulls,
    cast(api.latest_pulled_at as varchar) as latest_pulled_at,
    (select count(*) from {{ ref('stg_removed_complaints') }}) as removed_rows,
    (select count(*) from {{ ref('stg_complaints') }}) as staging_rows,
    fct.fact_rows,
    cast(fct.data_start as varchar) as data_start,
    cast(fct.data_end as varchar) as data_end,
    current_timestamp as built_at
from read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s
cross join (
    select count(distinct pulled_at) as api_pulls, max(pulled_at) as latest_pulled_at
    from {{ ref('stg_api_pull_days') }}
) as api
cross join (
    select count(*) as fact_rows, min(date_received) as data_start, max(date_received) as data_end
    from {{ ref('fct_complaints') }}
) as fct
