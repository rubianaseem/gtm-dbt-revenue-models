-- One row per HubSpot contact record (duplicates by email are resolved later in int_contacts__deduped).
select
    cast(id as varchar)                             as contact_id,
    {{ clean_email('email') }}                      as email,
    split_part({{ clean_email('email') }}, '@', 2)  as email_domain,
    firstname                                       as first_name,
    lastname                                        as last_name,
    lower(trim(lifecyclestage))                     as lifecycle_stage,
    {{ parse_ts('createdate') }}                    as created_at,
    hs_analytics_source                             as original_source,
    nullif(trim(notes), '')                         as notes_untrusted,
    _fivetran_synced                                as synced_at
from {{ source('hubspot', 'contacts') }}
where not {{ to_bool('is_deleted') }}
