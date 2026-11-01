-- One ordering for "the latest version of a complaint": newest data (as_of), then a pull over
-- the bulk file at equal as_of, then the most recent pull.
{% macro latest_version_order() -%}
order by as_of desc, (loaded_from = 'api') desc, pulled_at desc nulls last
{%- endmacro %}
