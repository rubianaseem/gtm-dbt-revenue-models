select
    cast(id as varchar)            as task_id,
    cast(what_id as varchar)       as opportunity_id,
    cast(owner_id as varchar)      as owner_id,
    task_type,
    try_cast(activity_date as date) as activity_date
from {{ source('salesforce', 'tasks') }}
