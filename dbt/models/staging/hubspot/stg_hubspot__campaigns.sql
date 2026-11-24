-- Deleted campaigns are kept (touches still reference them) and flagged so attribution can exclude them.
select
    cast(id as varchar)               as campaign_id,
    name                              as campaign_name,
    campaign_type,
    try_cast(start_date as date)      as start_date,
    {{ to_bool('is_deleted') }}       as is_deleted
from {{ source('hubspot', 'campaigns') }}
