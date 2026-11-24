-- Canonical stage, USD amount, company, owner and fiscal quarter for every live opportunity.
select
    o.opportunity_id,
    o.opportunity_name,
    o.account_domain,
    c.company_id,
    c.industry,
    o.owner_id,
    u.owner_name,
    u.territory,
    coalesce(u.is_active, false)                     as owner_is_active,
    o.primary_contact_email,
    o.stage_raw,
    m.stage,
    m.stage_order,
    m.is_closed,
    m.is_won,
    o.currency,
    o.amount_local,
    o.amount_local * fx.rate_to_usd                  as amount_usd,
    o.created_at,
    o.close_date,
    {{ fiscal_quarter('o.close_date') }}              as fiscal_quarter,
    o.lead_source
from {{ ref('stg_salesforce__opportunities') }} o
left join {{ ref('stage_map') }} m on m.raw_stage = lower(o.stage_raw)
left join {{ ref('fx_rates') }} fx on fx.currency = o.currency
left join {{ ref('stg_hubspot__companies') }} c on c.domain = o.account_domain
left join {{ ref('stg_salesforce__users') }} u on u.owner_id = o.owner_id
