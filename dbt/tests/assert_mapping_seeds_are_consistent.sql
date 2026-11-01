-- Mapping seeds: one row per key; every canonical credit card issue is on the current list,
-- except 'legacy' rows (an old issue with no current home keeps its own canonical value).
select 'duplicate family key' as problem, product || ' / ' || sub_product as key
from {{ ref('product_family_map') }} group by product, sub_product having count(*) > 1
union all
select 'duplicate issue key', product || ' / ' || issue
from {{ ref('credit_card_issue_map') }} group by product, issue having count(*) > 1
union all
select 'canonical issue not on the current list', canonical_issue
from {{ ref('credit_card_issue_map') }}
where match <> 'legacy' and canonical_issue not in (
    select issue from {{ ref('credit_card_issue_map') }}
    where product = 'Credit card' and match = 'exact'
)
