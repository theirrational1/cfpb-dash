-- Company match key: upper-cased, trimmed, inner whitespace collapsed (M2-07).
{% macro company_key(column) -%}
upper(regexp_replace(trim({{ column }}), '\s+', ' ', 'g'))
{%- endmacro %}
