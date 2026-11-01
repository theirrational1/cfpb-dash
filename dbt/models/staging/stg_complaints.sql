-- CLEANER Limit + Edit + types. zip_code and source_file dropped (docs/decisions/nulls.md).
-- CLEANER Null: each nullable column follows docs/decisions/nulls.md (tests in the yml).
-- The model contract (stg_complaints.yml) pins the column list and types.
-- Upsert (M2-03): the latest loaded version of each complaint wins; removed ones are left out
-- (counted in stg_removed_complaints).
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
    -- tags: meaningful blank (no tag applies) -> explicit booleans; raw values tested on source
    coalesce("Tags" like '%Older American%', false) as is_older_american,
    coalesce("Tags" like '%Servicemember%', false) as is_servicemember,
    "Submitted via" as submitted_via,
    "Company response to consumer" as company_response,
    -- blank on a closed or untimely complaint from 2015 = the company gave no public response;
    -- In progress (not yet available), status missing, and pre-2015 (structural) stay null
    case
        when "Company public response" is not null then "Company public response"
        when cast("Date received" as date) >= date '2015-01-01'
            and "Company response to consumer" <> 'In progress' then 'none_given'
    end as company_public_response,
    cast("Date received" as date) >= date '2015-01-01' as public_response_available,
    "Timely response?" = 'Yes' as timely
from {{ ref('stg_complaint_versions') }}
where cast("Complaint ID" as bigint) not in (
    select complaint_id from {{ ref('stg_removed_complaints') }}
)
qualify row_number() over (partition by "Complaint ID" order by loaded_at desc) = 1
