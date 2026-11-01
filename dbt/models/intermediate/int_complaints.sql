-- CLEANER Engineer: categories mapped across the 2017 and 2023 label revisions (seeds).
-- product_family: an exact (product, sub_product) row wins over the product's '*' default.
-- credit_card_issue: the current (2023+) credit card issue list, for credit card rows only.
with s as (select * from {{ ref('stg_complaints') }})

select
    s.*,
    coalesce(exact.product_family, dflt.product_family) as product_family,
    case
        when coalesce(exact.product_family, dflt.product_family) = 'credit_card'
            then cc.canonical_issue
    end as credit_card_issue
from s
left join {{ ref('product_family_map') }} as exact
    on s.product = exact.product and s.sub_product = exact.sub_product
left join {{ ref('product_family_map') }} as dflt
    on s.product = dflt.product and dflt.sub_product = '*'
left join {{ ref('credit_card_issue_map') }} as cc
    on s.product = cc.product and s.issue = cc.issue
