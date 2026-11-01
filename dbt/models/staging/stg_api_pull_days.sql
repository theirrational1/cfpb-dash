-- Which received days each API pull covered (including days with no complaints), and the
-- as_of (last_indexed) of the data it saw.
select
    cast(pulled_at as timestamptz) as pulled_at,
    cast(as_of as timestamptz) as as_of,
    cast(as_of_date_et as date) as as_of_date_et,
    cast(day as date) as day,
    rows
from {{ source('raw', 'api_pull_days') }}
