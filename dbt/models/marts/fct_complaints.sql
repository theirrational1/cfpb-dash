-- CLEANER Restrict. Grain: one complaint, all products. company is the canonical display
-- name (dim_company); raw product / issue labels are kept beside their mapped forms.
select
    i.complaint_id,
    i.date_received,
    i.date_sent_to_company,
    i.received_month,
    i.product_family,
    i.product,
    i.sub_product,
    i.issue,
    i.credit_card_issue,
    i.company_key,
    i.company_key || ' | ' || i.product_family as company_product_key,  -- peer groups
    d.company_name as company,
    i.state,
    i.submitted_via,
    i.company_response,
    i.is_closed,
    i.is_relief,
    i.is_monetary_relief,
    i.timely,
    i.forwarding_lag_days,
    i.public_response,
    i.public_response_available,
    i.is_older_american,
    i.is_servicemember
from {{ ref('int_complaints') }} as i
inner join {{ ref('dim_company') }} as d using (company_key)
