select
    cast(id as varchar)               as history_id,
    cast(opportunity_id as varchar)   as opportunity_id,
    trim(stage_name)                  as stage_raw,
    {{ parse_ts('created_date') }}    as stage_entered_at
from {{ source('salesforce', 'opportunity_history') }}
