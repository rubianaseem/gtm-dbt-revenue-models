-- Typing and cleaning only. No dedupe here on purpose: a duplicate id from the connector must fail the
-- unique test so a person decides what happened, rather than staging silently picking a row.
select
    cast(id as varchar)                              as opportunity_id,
    name                                             as opportunity_name,
    lower(trim(account_domain))                      as account_domain,
    nullif(trim(owner_id), '')                       as owner_id,
    {{ clean_email('primary_contact_email') }}       as primary_contact_email,
    trim(stage_name)                                 as stage_raw,
    try_cast(nullif(trim(amount), '') as double)     as amount_local,
    upper(trim(currency_iso_code))                   as currency,
    {{ parse_ts('created_date') }}                   as created_at,
    try_cast(close_date as date)                     as close_date,
    lead_source,
    nullif(trim(description), '')                    as description_untrusted,
    _fivetran_synced                                 as synced_at
from {{ source('salesforce', 'opportunities') }}
where not {{ to_bool('is_deleted') }}
