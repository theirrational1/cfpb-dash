-- Grain: one complaint.
select
    complaint_id,
    date_received,
    company,
    product
from {{ ref('stg_complaints') }}
