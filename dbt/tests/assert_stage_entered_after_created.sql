-- A stage cannot start more than a day before its opportunity was created. Breaks show timezone or format drift.
select h.opportunity_id, h.stage_entered_at, o.created_at
from {{ ref('stg_salesforce__opportunity_history') }} h
join {{ ref('stg_salesforce__opportunities') }} o using (opportunity_id)
where h.stage_entered_at < o.created_at - interval 1 day
