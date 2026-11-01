-- The snapshot date, in one place: the bulk snapshot date, or the US Eastern date of the
-- newest pull's data (last_indexed) if later. Used by the stamp and the peer-group window.
select greatest(
    cast(s.snapshot_date as date),
    coalesce((select max(as_of_date_et) from {{ ref('stg_api_pull_days') }}), date '0001-01-01')
) as snapshot_date
from read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true) as s
