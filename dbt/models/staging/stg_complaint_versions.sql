-- Every loaded version of every complaint: the bulk file plus each API pull (M2-03 upsert).
-- as_of = when CFPB produced the data (bulk: the CSV's generation time; pull: the API's
-- last_indexed). Versions are ordered by as_of, never by download date (review 3 #1).
select
    b.* exclude (source_file),
    cast(s.generated_at as timestamptz) as as_of,
    'bulk' as loaded_from,
    cast(null as timestamptz) as pulled_at
from {{ source('raw', 'complaints') }} as b
cross join read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s

union all by name

select
    a.* exclude (pulled_day),
    'api' as loaded_from
from {{ source('raw', 'api_complaints') }} as a
