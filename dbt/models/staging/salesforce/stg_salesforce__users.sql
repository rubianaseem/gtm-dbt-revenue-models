select
    cast(id as varchar)         as owner_id,
    name                        as owner_name,
    user_role,
    territory,
    {{ to_bool('is_active') }}  as is_active
from {{ source('salesforce', 'users') }}
