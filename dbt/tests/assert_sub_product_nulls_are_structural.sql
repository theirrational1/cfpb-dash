-- nulls.md: sub_product is null only in label eras that had no sub-products
-- (seed no_sub_product_eras); stray nulls elsewhere (error, ~136 rows) are capped.
select count(*) as stray_nulls
from {{ ref('stg_complaints') }} as s
left join {{ ref('no_sub_product_eras') }} as e
    on s.product = e.product and s.date_received < e.received_before
where s.sub_product is null and e.product is null
having count(*) > {{ var('sub_product_stray_null_cap') }}
