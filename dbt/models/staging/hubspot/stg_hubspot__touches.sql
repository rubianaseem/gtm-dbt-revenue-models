select
    cast(id as varchar)            as touch_id,
    cast(contact_id as varchar)    as contact_id,
    cast(campaign_id as varchar)   as campaign_id,
    touch_type,
    {{ parse_ts('occurred_at') }}  as occurred_at
from {{ source('hubspot', 'touches') }}
