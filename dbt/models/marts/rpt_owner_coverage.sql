-- Pipeline coverage per owner per quarter that has a quota. Flags inactive owners still holding pipeline.
with pipe as (
    select owner_id, fiscal_quarter,
           sum(amount_usd) filter (where not is_closed) as open_pipeline_usd,
           sum(amount_usd) filter (where is_won)        as closed_won_usd
    from {{ ref('int_opportunities__enriched') }}
    group by 1, 2
)
select
    q.owner_id,
    u.owner_name,
    q.fiscal_quarter,
    cast(q.quota_usd as double)                                              as quota_usd,
    cast(coalesce(p.open_pipeline_usd, 0) as double)                         as open_pipeline_usd,
    cast(coalesce(p.closed_won_usd, 0) as double)                            as closed_won_usd,
    cast(round(coalesce(p.open_pipeline_usd, 0) / nullif(q.quota_usd - coalesce(p.closed_won_usd, 0), 0), 2) as double) as coverage_ratio,
    coalesce(u.is_active, false)                                             as owner_is_active,
    case
        when not coalesce(u.is_active, false) and coalesce(p.open_pipeline_usd, 0) > 0 then 'inactive_owner_holds_pipeline'
        when coalesce(p.open_pipeline_usd, 0) / nullif(q.quota_usd - coalesce(p.closed_won_usd, 0), 0) < 3 then 'below_3x'
        else 'ok'
    end                                                                      as coverage_flag
from {{ ref('quotas') }} q
left join pipe p on p.owner_id = q.owner_id and p.fiscal_quarter = q.fiscal_quarter
left join {{ ref('stg_salesforce__users') }} u on u.owner_id = q.owner_id
