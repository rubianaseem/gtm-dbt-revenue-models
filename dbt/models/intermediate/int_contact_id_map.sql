-- Maps every contact id (including merged duplicates) to its person-level contact_key.
select contact_id, coalesce(email, 'id:' || contact_id) as contact_key
from {{ ref('stg_hubspot__contacts') }}
