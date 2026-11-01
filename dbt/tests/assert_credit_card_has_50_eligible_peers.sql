-- M0-13 evidence (docs/profiling/07_threshold.md): at >= 100 complaints in 2025-10..2026-09,
-- credit card has 50 eligible companies. Full data only (the fixtures have 3 companies).
{{ config(tags=['full_data']) }}
select count(*) as n_eligible
from {{ ref('dim_company_product') }}
where product_family = 'credit_card' and peer_status = 'eligible'
having count(*) != 50
