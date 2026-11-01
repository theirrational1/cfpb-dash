-- Peer groups (PRD §8, M3-03): one row per (company, product family) that has complaints.
-- Eligible for rate comparisons: >= var('min_volume_threshold') complaints in the 12 full
-- calendar months before the snapshot month. Eligible companies get a complaint-volume tier
-- (ntile by that count within the family; labels and ties per params/volume_tiers.v1.yaml).
-- A tier ranks complaint VOLUME, not company size.
{% set labels = var('volume_tier_labels') %}
with snap as (select snapshot_date from {{ ref('int_snapshot_date') }}),

window_ as (
    select
        cast(date_trunc('month', snapshot_date) - interval 12 month as date) as window_start,
        cast(date_trunc('month', snapshot_date) - interval 1 day as date) as window_end
    from snap
),

counts as (
    select
        f.company_key,
        f.product_family,
        w.window_start,
        w.window_end,
        count(*) filter (
            where f.date_received between w.window_start and w.window_end
        ) as complaints_trailing_12m
    from {{ ref('fct_complaints') }} as f
    cross join window_ as w
    group by all
),

status as (
    select
        *,
        case when complaints_trailing_12m >= {{ var('min_volume_threshold') }}
            then 'eligible' else 'below_threshold' end as peer_status
    from counts
),

ranked as (
    select
        *,
        row_number() over (
            partition by product_family, peer_status
            order by complaints_trailing_12m desc, company_key
        ) as rank_in_status,
        ntile({{ labels | length }}) over (
            partition by product_family, peer_status
            order by complaints_trailing_12m desc, company_key
        ) as tile,
        count(*) filter (where peer_status = 'eligible') over (
            partition by product_family
        ) as n_eligible_in_family
    from status
)

select
    company_key || ' | ' || product_family as company_product_key,
    company_key,
    product_family,
    window_start,
    window_end,
    complaints_trailing_12m,
    peer_status,
    case when peer_status = 'eligible' then
        case tile {% for label in labels %}when {{ loop.index }} then '{{ label }}' {% endfor %}end
    end as volume_tier,
    case when peer_status = 'eligible' then rank_in_status end as rank_in_family,
    n_eligible_in_family,
    {{ var('min_volume_threshold_version') }} as threshold_version,
    {{ var('volume_tiers_version') }} as tiers_version
from ranked
