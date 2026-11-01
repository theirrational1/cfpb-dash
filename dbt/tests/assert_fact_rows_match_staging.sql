-- Restrict reconciliation: the fact keeps every staged complaint (grain: one complaint).
select n_staging, n_fact
from (select count(*) as n_staging from {{ ref('stg_complaints') }})
cross join (select count(*) as n_fact from {{ ref('fct_complaints') }})
where n_staging != n_fact
