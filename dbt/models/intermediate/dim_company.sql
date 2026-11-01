-- One row per canonical company (M2-07). company_key = normalized name (case and spacing);
-- reviewed aliases (seed company_aliases: punctuation or the same legal form spelled
-- differently) fold into their canonical key. Acquisitions are NOT merged.
-- company_name = the most frequent raw spelling of the canonical key.
with names as (
    select company, {{ company_key('company') }} as raw_key, count(*) as n
    from {{ ref('stg_complaints') }}
    group by all
),

aliases as (
    select {{ company_key('alias_name') }} as alias_key,
           {{ company_key('canonical_name') }} as canonical_key
    from {{ ref('company_aliases') }}
),

keyed as (
    select names.*, coalesce(aliases.canonical_key, names.raw_key) as company_key
    from names left join aliases on names.raw_key = aliases.alias_key
)

select
    company_key,
    first(company order by n desc, company) filter (where raw_key = company_key) as company_name,
    count(*) as n_raw_names,
    sum(n) as n_complaints
from keyed
group by company_key
