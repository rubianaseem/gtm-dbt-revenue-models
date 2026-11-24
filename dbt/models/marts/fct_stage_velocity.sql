-- Days spent in each open stage before moving on, from completed spells only.
select
    stage,
    cast(min(stage_order) as integer)                                   as stage_order,
    cast(count(*) as integer)                                           as completed_spells,
    cast(round(median(days_in_stage), 1) as double)                     as median_days,
    cast(round(quantile_cont(days_in_stage, 0.75), 1) as double)        as p75_days
from {{ ref('int_opportunity__stage_spells') }}
where stage_exited_at is not null and stage_order <= 5
group by 1
