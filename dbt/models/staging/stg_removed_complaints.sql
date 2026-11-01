-- Complaints whose received day was re-pulled after their latest version, but which the
-- latest pull of that day no longer contains: removed from the public database since. They
-- leave staging, and are counted here (a counted exclusion, never a silent drop).
with latest as (
    select "Complaint ID" as complaint_id, cast("Date received" as date) as date_received,
           loaded_at, loaded_from
    from {{ ref('stg_complaint_versions') }}
    qualify row_number() over (partition by "Complaint ID" order by loaded_at desc) = 1
),

last_pull as (
    select day, max(pulled_at) as pulled_at from {{ ref('stg_api_pull_days') }} group by day
)

select
    cast(l.complaint_id as bigint) as complaint_id,
    l.date_received,
    l.loaded_from as last_seen_in,
    l.loaded_at as last_seen_at,
    p.pulled_at as missing_from_pull_at
from latest as l
inner join last_pull as p on l.date_received = p.day
where l.loaded_at < p.pulled_at
