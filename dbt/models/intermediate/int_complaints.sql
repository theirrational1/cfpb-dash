-- CLEANER Engineer: categories mapped across the 2017 and 2023 label revisions (seeds).
-- product_family: an exact (product, sub_product) row wins over the product's '*' default.
-- credit_card_issue: the current (2023+) credit card issue list, for credit card rows only.
-- company_key: canonical company (dim_company), via the same key and alias seed.
-- forwarding_lag_days keeps the -1 artifact (nulls.md); relief flags come from seed
-- company_responses (no string matching); public_response merges the two opt-out wordings.
with s as (select * from {{ ref('stg_complaints') }})

select
    s.*,
    coalesce(exact.product_family, dflt.product_family) as product_family,
    case
        when coalesce(exact.product_family, dflt.product_family) = 'credit_card'
            then cc.canonical_issue
    end as credit_card_issue,
    coalesce(
        {{ company_key('al.canonical_name') }}, {{ company_key('s.company') }}
    ) as company_key,
    date_diff('day', s.date_received, s.date_sent_to_company) as forwarding_lag_days,
    cast(date_trunc('month', s.date_received) as date) as received_month,
    coalesce(r.is_closed, false) as is_closed,
    r.is_relief,
    r.is_monetary_relief,
    pr.canonical_public_response as public_response
from s
left join {{ ref('product_family_map') }} as exact
    on s.product = exact.product and s.sub_product = exact.sub_product
left join {{ ref('product_family_map') }} as dflt
    on s.product = dflt.product and dflt.sub_product = '*'
left join {{ ref('credit_card_issue_map') }} as cc
    on s.product = cc.product and s.issue = cc.issue
left join {{ ref('company_aliases') }} as al
    on {{ company_key('s.company') }} = {{ company_key('al.alias_name') }}
left join {{ ref('company_responses') }} as r on s.company_response = r.company_response
left join {{ ref('public_responses') }} as pr
    on s.company_public_response = pr.public_response
