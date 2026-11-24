{# Every value must exist in a mapping seed. normalise=true compares lower(trim(value)). Returns the unmapped values with counts. #}
{% test mapped_in_seed(model, column_name, seed, seed_column, normalise=true) %}
with vals as (
    select {% if normalise %}lower(trim({{ column_name }})){% else %}{{ column_name }}{% endif %} as value
    from {{ model }}
    where {{ column_name }} is not null
)
select value as unmapped_value, count(*) as row_count
from vals
where value not in (select {{ seed_column }} from {{ ref(seed) }})
group by 1
{% endtest %}
