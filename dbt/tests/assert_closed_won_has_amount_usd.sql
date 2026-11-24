-- Closed-won revenue with no USD amount (missing amount or currency with no FX rate) under-reports bookings.
select opportunity_id, stage, amount_local, currency
from {{ ref('int_opportunities__enriched') }}
where is_won and amount_usd is null
