-- nulls.md: forwarding_lag_days keeps -1 (sent a day before received, 7,050 rows); the count
-- is pinned under a cap and nothing below -1 may appear.
select count(*) filter (where forwarding_lag_days < 0) as negative,
       min(forwarding_lag_days) as min_lag
from {{ ref('int_complaints') }}
having count(*) filter (where forwarding_lag_days < 0) > {{ var('negative_lag_cap') }}
    or min(forwarding_lag_days) < -1
