select
    cast(id as varchar)          as company_id,
    name                         as company_name,
    lower(trim(domain))          as domain,
    industry,
    upper(trim(country))         as country,
    {{ parse_ts('createdate') }} as created_at
from {{ source('hubspot', 'companies') }}
