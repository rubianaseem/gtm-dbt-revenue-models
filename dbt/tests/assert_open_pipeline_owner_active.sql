{{ config(severity='warn') }}
-- Open pipeline held by an inactive or unknown owner. Warn only: RevOps reassigns in the CRM.
select opportunity_id, owner_id, amount_usd
from {{ ref('int_opportunities__enriched') }}
where not is_closed and not owner_is_active
