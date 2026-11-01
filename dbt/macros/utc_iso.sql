-- A timestamp as a UTC ISO string, independent of the machine's time zone.
{% macro utc_iso(ts) -%}
strftime(timezone('UTC', cast({{ ts }} as timestamptz)), '%Y-%m-%dT%H:%M:%SZ')
{%- endmacro %}
