-- CLEANER Limit + Edit + types. zip_code and source_file dropped (docs/decisions/nulls.md).
-- Null handling per nulls.md is M2-05; this is the M1 skeleton.
select
    cast("Complaint ID" as bigint) as complaint_id,
    cast("Date received" as date) as date_received,
    cast("Date sent to company" as date) as date_sent_to_company,
    "Product" as product,
    "Sub-product" as sub_product,
    "Issue" as issue,
    "Sub-issue" as sub_issue,
    "Company" as company,
    "State" as state,
    "Tags" as tags,
    "Submitted via" as submitted_via,
    "Company response to consumer" as company_response,
    "Company public response" as company_public_response,
    "Timely response?" as timely
from {{ source('raw', 'complaints') }}
