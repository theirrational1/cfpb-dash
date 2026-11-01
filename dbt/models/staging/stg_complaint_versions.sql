-- Every loaded version of every complaint: the bulk file plus each API pull (M2-03 upsert).
-- loaded_at orders versions: the bulk's snapshot date, or the pull's timestamp.
select
    b.* exclude (source_file),
    timezone('UTC', cast(s.snapshot_date as timestamp)) as loaded_at,  -- bulk date, UTC midnight
    'bulk' as loaded_from
from {{ source('raw', 'complaints') }} as b
cross join read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s

union all by name

select
    a.* exclude (pulled_at, pulled_day),
    a.pulled_at as loaded_at,
    'api' as loaded_from
from {{ source('raw', 'api_complaints') }} as a
