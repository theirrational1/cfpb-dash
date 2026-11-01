-- Coverage source table (PRD §5 coverage panel, §6 get_data_coverage; M3-04): freshness, every
-- counted exclusion behind the metrics, and the fixed caveats. One row per (item, scope).
-- Counts are from fct_complaints unless noted; value is text so dates and counts share a column.
with f as (select * from {{ ref('fct_complaints') }}),
snap as (
    select
        cast(i.snapshot_date as varchar) as snapshot_date,
        {{ utc_iso('s.generated_at') }} as bulk_generated_at
    from {{ ref('int_snapshot_date') }} as i
    cross join read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s
),

freshness as (
    select 'snapshot_date' as item, 'all' as scope, snapshot_date as value,
           'Bulk snapshot date, or the US Eastern date of the newest API pull data' as note
    from snap
    union all
    select 'bulk_generated_at', 'all', bulk_generated_at, 'When CFPB generated the bulk file (UTC)'
    from snap
    union all
    select 'latest_pull_as_of', 'all', {{ utc_iso('max(as_of)') }},
           'API last_indexed of the newest pull; null if none'
    from {{ ref('stg_api_pull_days') }}
    union all
    select 'data_start', 'all', cast(min(date_received) as varchar), 'First complaint received'
    from f
    union all
    select 'data_end', 'all', cast(max(date_received) as varchar), 'Last complaint received'
    from f
    union all
    select 'narrative_cutoff', 'all', '{{ var("narrative_cutoff") }}',
           'Narrative metrics and the issue deep-dive use complaints received on or before this'
),

counts as (
    select 'complaints' as item, 'all' as scope, count(*) as n,
           'Complaints in the warehouse' as note from f
    union all
    select 'open_in_progress', 'all', count(*) filter (where company_response = 'In progress'),
           'Open: excluded from relief, monetary relief, timeliness, public response' from f
    union all
    select 'not_closed_untimely', 'all',
           count(*) filter (where company_response = 'Untimely response'),
           'Not closed: excluded from relief rates; counts as a (late) response for timeliness'
    from f
    union all
    select 'status_missing', 'all', count(*) filter (where company_response is null),
           'company_response missing (error): excluded from response-based rates' from f
    union all
    select 'relief_outcome_unknown', 'all', count(*) filter (where company_response = 'Closed'),
           'Bare Closed (2011-17): outcome not recorded, excluded from relief rates' from f
    union all
    select 'relief_kind_unknown', 'all',
           count(*) filter (where company_response = 'Closed with relief'),
           '2011-12 Closed with relief: kind not recorded, excluded from monetary relief rate'
    from f
    union all
    select 'issue_missing', 'all', count(*) filter (where issue is null),
           'Null issue (error): excluded from issue shares' from f
    union all
    select 'public_response_before_2015', 'all',
           count(*) filter (where not public_response_available),
           'Before the public-response option: excluded from public response rate' from f
    union all
    select 'sub_product_unknown', 'all', count(*) filter (where sub_product is null),
           'No sub-product (structural eras plus a few stray errors; nulls.md)' from f
    union all
    select 'removed_from_public_database', 'all', count(*),
           'Complaints a newer source no longer contains: excluded everywhere'
    from {{ ref('stg_removed_complaints') }}
    union all
    select 'below_threshold_companies', product_family, count(*) filter (
               where peer_status = 'below_threshold'),
           'Companies under the volume threshold: excluded from peer rate comparisons'
    from {{ ref('dim_company_product') }} group by product_family
    union all
    select 'eligible_companies', product_family, count(*) filter (where peer_status = 'eligible'),
           'Companies eligible for peer comparisons (threshold v{{ var("min_volume_threshold_version") }})'
    from {{ ref('dim_company_product') }} group by product_family
),

caveats as (
    select * from (values
        ('caveat_small_banks', 'all', cast(null as varchar),
         'Complaints about banks with under $10B in assets are not published (referred elsewhere)'),
        ('caveat_not_a_sample', 'all', null,
         'The database is not a statistical sample of consumer experiences'),
        ('caveat_unverified', 'all', null,
         'Complaints are unverified allegations; never evidence that a company broke the law'),
        ('caveat_counts_not_rates', 'all', null,
         'No size denominators: complaint counts are not rates and do not measure company size'),
        ('caveat_consumer_labels', 'all', null,
         'Product and issue labels are chosen by consumers and were revised in 2017 and 2023')
    ) as t(item, scope, value, note)
)

select item, scope, value, note from freshness
union all
select item, scope, cast(n as varchar), note from counts
union all
select item, scope, value, note from caveats
