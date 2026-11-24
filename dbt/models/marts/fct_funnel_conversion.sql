-- How many opportunities ever reached each stage (from history) and how many moved on to a later stage.
with reached as (
    select opportunity_id, stage, stage_order from {{ ref('int_opportunity__stage_spells') }} where stage_order <= 5
    union
    select opportunity_id, 'Closed Won', 6 from {{ ref('int_opportunity__stage_spells') }} where stage = 'Closed Won'
),
max_order as (
    select opportunity_id, max(stage_order) as max_order from {{ ref('int_opportunity__stage_spells') }}
    where stage <> 'Closed Lost' group by 1
),
counts as (
    select r.stage, r.stage_order,
           count(distinct r.opportunity_id) as reached,
           count(distinct r.opportunity_id) filter (where m.max_order > r.stage_order) as progressed
    from reached r join max_order m using (opportunity_id)
    group by 1, 2
)
select
    stage,
    cast(stage_order as integer)                                        as stage_order,
    cast(reached as integer)                                            as reached,
    cast(progressed as integer)                                         as progressed,
    cast(round(100.0 * progressed / nullif(reached, 0), 1) as double)   as conversion_to_next_pct
from counts
