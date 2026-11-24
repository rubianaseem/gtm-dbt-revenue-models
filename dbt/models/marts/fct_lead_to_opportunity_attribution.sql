-- One row per live opportunity: first and last pre-creation campaign touch (null when none matched).
with firsts as (select * from {{ ref('int_touches__attributed') }} where touch_seq = 1),
     lasts  as (select * from {{ ref('int_touches__attributed') }} where touch_seq_desc = 1),
     n      as (select opportunity_id, count(*) as touches from {{ ref('int_touches__attributed') }} group by 1)
select
    o.opportunity_id,
    o.fiscal_quarter,
    cast(o.amount_usd as double)                                                     as amount_usd,
    f.campaign_id                                                                    as first_touch_campaign_id,
    l.campaign_id                                                                    as last_touch_campaign_id,
    cast(coalesce(n.touches, 0) as integer)                                          as touches_before_create,
    cast(date_diff('day', f.occurred_at, o.created_at) as integer)                   as days_first_touch_to_opp,
    case when f.campaign_id is null then 'unattributed' else 'campaign' end          as attribution_status
from {{ ref('int_opportunities__enriched') }} o
left join firsts f using (opportunity_id)
left join lasts l using (opportunity_id)
left join n using (opportunity_id)
