-- Provenance stamp: the raw snapshot this warehouse was built from, frozen at build time.
-- query_metric reads provenance from here, so labels always match the data queried.
select
    cast(snapshot_date as varchar) as snapshot_date,
    cast(source_sha256 as varchar) as source_sha256,
    cast(source_path as varchar) as source_path,
    cast("rows" as bigint) as source_rows,
    cast(built_at as varchar) as ingested_at,
    current_timestamp as built_at
from read_json('{{ env_var("CFPB_SNAPSHOT_JSON") }}', auto_detect = true)
