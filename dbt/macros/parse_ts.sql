{#
  CRM exports mix three timestamp styles: '...Z', '...+01:00' and naive '2026-10-05 11:00:00'.
  Offset-aware strings are converted to UTC. Naive strings are treated as UTC (HubSpot and Salesforce
  APIs return UTC; naive values come from CSV exports). Anything unparseable becomes NULL so a
  not_null test fails loudly instead of the model silently guessing.
#}
{% macro parse_ts(col) -%}
    case
        when regexp_matches(trim({{ col }}), '(Z|[+-][0-9]{2}:?[0-9]{2})$')
            then (try_cast(trim({{ col }}) as timestamptz) at time zone 'UTC')
        else try_cast(trim({{ col }}) as timestamp)
    end
{%- endmacro %}
