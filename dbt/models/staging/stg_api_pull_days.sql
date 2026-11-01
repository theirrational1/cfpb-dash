-- Which received days each API pull covered (including days with no complaints).
select cast(pulled_at as timestamptz) as pulled_at, cast(day as date) as day, rows
from {{ source('raw', 'api_pull_days') }}
