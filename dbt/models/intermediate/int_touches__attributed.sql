-- Marketing touches that happened before an opportunity was created, matched person-to-opportunity by the
-- primary contact email. Deleted campaigns are excluded from credit.
with touches as (
    select t.touch_id, t.occurred_at, t.campaign_id, t.touch_type, m.contact_key
    from {{ ref('stg_hubspot__touches') }} t
    join {{ ref('int_contact_id_map') }} m on m.contact_id = t.contact_id
    join {{ ref('stg_hubspot__campaigns') }} c on c.campaign_id = t.campaign_id and not c.is_deleted
)
select
    o.opportunity_id,
    t.touch_id,
    t.campaign_id,
    t.touch_type,
    t.occurred_at,
    row_number() over (partition by o.opportunity_id order by t.occurred_at, t.touch_id)            as touch_seq,
    row_number() over (partition by o.opportunity_id order by t.occurred_at desc, t.touch_id desc)  as touch_seq_desc
from {{ ref('int_opportunities__enriched') }} o
join touches t on t.contact_key = o.primary_contact_email and t.occurred_at <= o.created_at
