-- The pipeline mart must equal the sum of open opportunities it was built from (to the cent).
with mart as (select coalesce(sum(pipeline_usd), 0) as v from {{ ref('fct_pipeline_snapshot') }}),
     src  as (select coalesce(sum(amount_usd), 0) as v from {{ ref('int_opportunities__enriched') }} where not is_closed)
select mart.v as mart_pipeline_usd, src.v as source_pipeline_usd
from mart, src
where abs(mart.v - src.v) > 0.01
