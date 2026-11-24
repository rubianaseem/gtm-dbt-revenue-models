{% macro clean_email(col) -%}
    nullif(lower(trim({{ col }})), '')
{%- endmacro %}

{% macro to_bool(col) -%}
    coalesce(lower(trim({{ col }})) in ('true', 't', '1', 'yes'), false)
{%- endmacro %}

{% macro fiscal_quarter(date_col) -%}
    cast(year({{ date_col }}) as varchar) || '-Q' || cast(quarter({{ date_col }}) as varchar)
{%- endmacro %}
