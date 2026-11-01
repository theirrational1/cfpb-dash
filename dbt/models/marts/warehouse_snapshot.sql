-- Provenance stamp: the raw snapshot this warehouse was built from, frozen at build time.
-- query_metric reads provenance from here, so labels always match the data queried.
-- It refs the fact table and the spine so a failed build skips it and keeps the old stamp;
-- read_snapshot_stamp then refuses to serve if staging or the fact moved without it.
-- snapshot_date: int_snapshot_date (bulk date, or the Eastern date of the newest pull's data;
-- never the clock time a pull ran). Built last: it also depends on the peer groups.
-- depends_on: {{ ref('metricflow_time_spine') }}
-- depends_on: {{ ref('dim_company_product') }}
select
    cast((select snapshot_date from {{ ref('int_snapshot_date') }}) as varchar) as snapshot_date,
    cast(s.snapshot_date as varchar) as bulk_snapshot_date,
    cast(s.generated_at as varchar) as bulk_generated_at,
    cast(s.dropped_since_previous as bigint) as bulk_dropped_since_previous,
    cast(s.source_sha256 as varchar) as source_sha256,
    cast(s.source_path as varchar) as source_path,
    cast(s."rows" as bigint) as source_rows,
    cast(s.built_at as varchar) as ingested_at,
    api.api_pulls,
    cast(api.latest_pulled_at as varchar) as latest_pulled_at,
    cast(api.latest_as_of as varchar) as latest_pull_as_of,
    (select count(*) from {{ ref('stg_removed_complaints') }}) as removed_rows,
    (select count(*) from {{ ref('stg_complaints') }}) as staging_rows,
    fct.fact_rows,
    cast(fct.data_start as varchar) as data_start,
    cast(fct.data_end as varchar) as data_end,
    '{{ invocation_id }}' as dbt_invocation_id,  -- ties the stamp to target/ artifacts
    current_timestamp as built_at
from read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s
cross join (
    select count(distinct pulled_at) as api_pulls, max(pulled_at) as latest_pulled_at,
           max(as_of) as latest_as_of, max(as_of_date_et) as latest_as_of_date_et
    from {{ ref('stg_api_pull_days') }}
) as api
cross join (
    select count(*) as fact_rows, min(date_received) as data_start, max(date_received) as data_end
    from {{ ref('fct_complaints') }}
) as fct
