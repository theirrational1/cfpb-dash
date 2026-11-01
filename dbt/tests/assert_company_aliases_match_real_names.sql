-- M2-07 match-rate check on the full data: every alias and canonical name in the seed is a
-- real raw company name (a stale alias would silently match nothing). Tagged full_data:
-- the small test fixtures don't contain these companies.
{{ config(tags=['full_data']) }}
select name
from (
    select alias_name as name from {{ ref('company_aliases') }}
    union all
    select canonical_name from {{ ref('company_aliases') }}
)
where {{ company_key('name') }} not in (
    select {{ company_key('company') }} from {{ ref('stg_complaints') }}
)
