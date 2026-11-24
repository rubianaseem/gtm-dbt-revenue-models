-- One row per time an opportunity entered a canonical stage. Consecutive repeats of the same stage
-- (label variants, re-saves) collapse into one spell. Spells end when the next stage starts.
with hist as (
    select h.opportunity_id, h.stage_entered_at, m.stage, m.stage_order
    from {{ ref('stg_salesforce__opportunity_history') }} h
    join {{ ref('stage_map') }} m on m.raw_stage = lower(h.stage_raw)
    where h.stage_entered_at is not null
),
marked as (
    select *, lag(stage) over (partition by opportunity_id order by stage_entered_at) as prev_stage
    from hist
),
spells as (
    select opportunity_id, stage, stage_order, stage_entered_at
    from marked
    where prev_stage is null or prev_stage <> stage
)
select
    opportunity_id,
    stage,
    stage_order,
    stage_entered_at,
    lead(stage_entered_at) over (partition by opportunity_id order by stage_entered_at) as stage_exited_at,
    lead(stage) over (partition by opportunity_id order by stage_entered_at)            as next_stage,
    date_diff('hour', stage_entered_at,
        lead(stage_entered_at) over (partition by opportunity_id order by stage_entered_at)) / 24.0 as days_in_stage
from spells
