-- One row per person. HubSpot dedupes contacts by email; exports still carry duplicates that differ only by
-- case or whitespace. The most recently created record wins; every merged id is kept for joins.
with ranked as (
    select
        *,
        coalesce(email, 'id:' || contact_id) as contact_key,
        row_number() over (partition by coalesce(email, 'id:' || contact_id) order by created_at desc, contact_id desc) as rn,
        count(*) over (partition by coalesce(email, 'id:' || contact_id)) as records_merged
    from {{ ref('stg_hubspot__contacts') }}
)
select contact_key, contact_id as surviving_contact_id, email, email_domain, first_name, last_name,
       lifecycle_stage, created_at, original_source, records_merged
from ranked
where rn = 1
