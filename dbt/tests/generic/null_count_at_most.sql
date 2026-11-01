-- Rare "error" nulls (docs/decisions/nulls.md): tolerated up to a cap, so growth is noticed.
{% test null_count_at_most(model, column_name, max_nulls) %}
select count(*) as n_null
from {{ model }}
where {{ column_name }} is null
having count(*) > {{ max_nulls }}
{% endtest %}
