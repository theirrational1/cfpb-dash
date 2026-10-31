-- Daily spine bounded to the data's date range, so zero-filled metrics never extend past the
-- snapshot (or before the first complaint).
select cast(range as date) as date_day
from range(
    (select min(date_received) from {{ ref('stg_complaints') }}),
    (select max(date_received) from {{ ref('stg_complaints') }}) + interval 1 day,
    interval 1 day
)
