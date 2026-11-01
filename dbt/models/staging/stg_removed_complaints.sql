-- Complaints removed from the public database: a newer complete source covering their
-- received day no longer contains them. Complete sources: each pull for the days it covered,
-- and the bulk file for every day up to its last received day. They leave staging and are
-- counted here (a counted exclusion, never a silent drop).
with latest as (
    select "Complaint ID" as complaint_id, cast("Date received" as date) as date_received,
           as_of, loaded_from
    from {{ ref('stg_complaint_versions') }}
    qualify row_number() over (partition by "Complaint ID" {{ latest_version_order() }}) = 1
),

pull_cover as (
    select day, max(as_of) as covered_as_of from {{ ref('stg_api_pull_days') }} group by day
),

bulk as (
    select max(as_of) as bulk_as_of, max(cast("Date received" as date)) as bulk_last_day
    from {{ ref('stg_complaint_versions') }}
    where loaded_from = 'bulk'
),

covered as (
    select
        l.*,
        greatest(
            coalesce(p.covered_as_of, timestamptz '0001-01-01 00:00:00+00'),
            case when l.date_received <= b.bulk_last_day then b.bulk_as_of
                 else timestamptz '0001-01-01 00:00:00+00' end
        ) as newest_cover
    from latest as l
    left join pull_cover as p on l.date_received = p.day
    cross join bulk as b
)

select
    cast(complaint_id as bigint) as complaint_id,
    date_received,
    loaded_from as last_seen_in,
    as_of as last_seen_as_of,
    newest_cover as missing_from_source_as_of
from covered
where newest_cover > as_of
