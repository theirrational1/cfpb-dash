-- A complaint appears at most once per load (bulk file or pull). Staging keeps the latest
-- version per complaint, so a duplicate inside one load must fail here, not be deduplicated.
select "Complaint ID", loaded_from, pulled_at, count(*) as n
from {{ ref('stg_complaint_versions') }}
group by all
having count(*) > 1
