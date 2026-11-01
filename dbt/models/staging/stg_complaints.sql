-- CLEANER Limit + Edit + types. zip_code and source_file dropped (docs/decisions/nulls.md).
-- The model contract (stg_complaints.yml) pins the column list and types.
select
    cast("Complaint ID" as bigint) as complaint_id,
    cast("Date received" as date) as date_received,
    cast("Date sent to company" as date) as date_sent_to_company,
    "Product" as product,
    "Sub-product" as sub_product,
    "Issue" as issue,
    "Sub-issue" as sub_issue,
    trim("Company") as company,
    "State" as state,
    "Tags" as tags,
    "Submitted via" as submitted_via,
    "Company response to consumer" as company_response,
    "Company public response" as company_public_response,
    "Timely response?" = 'Yes' as timely
from {{ source('raw', 'complaints') }}
