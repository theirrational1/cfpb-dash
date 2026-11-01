-- Raw files agree with their metadata (catches a half-finished ingest), and staging holds
-- every distinct complaint across bulk + pulls except the counted removals.
with raw as (
    select
        (select count(*) from {{ source('raw', 'complaints') }}) as bulk_rows,
        (select source_rows from {{ ref('warehouse_snapshot') }}) as bulk_expected,
        (select count(*) from {{ source('raw', 'api_complaints') }}) as api_rows,
        (select coalesce(sum(rows), 0) from {{ ref('stg_api_pull_days') }}) as api_expected,
        (select count(distinct "Complaint ID") from {{ ref('stg_complaint_versions') }})
            - (select count(*) from {{ ref('stg_removed_complaints') }}) as staging_expected,
        (select count(*) from {{ ref('stg_complaints') }}) as staging_rows
)
select * from raw
where bulk_rows != bulk_expected or api_rows != api_expected or staging_rows != staging_expected
