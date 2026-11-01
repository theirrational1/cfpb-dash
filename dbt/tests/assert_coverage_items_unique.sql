-- data_coverage has one row per (item, scope).
select item, scope, count(*) from {{ ref('data_coverage') }} group by all having count(*) > 1
