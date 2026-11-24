{# Fails rows dated after the as-of date (plus a one-day grace for timezone edges). Catches day/month swaps and offset bugs. #}
{% test not_in_future(model, column_name) %}
select {{ column_name }} as failing_value, *
from {{ model }}
where cast({{ column_name }} as date) > cast('{{ var("as_of_date") }}' as date) + interval 1 day
{% endtest %}
