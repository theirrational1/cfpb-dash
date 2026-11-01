-- M2-06: every credit card issue label (any era) maps onto the current issue list.
select product, issue, count(*) as n
from {{ ref('int_complaints') }}
where product_family = 'credit_card' and issue is not null and credit_card_issue is null
group by all
