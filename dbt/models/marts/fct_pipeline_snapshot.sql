-- Open pipeline as of var('as_of_date'), by owner, fiscal quarter and stage. Amounts in USD.
select
    cast('{{ var("as_of_date") }}' as date)                          as as_of_date,
    owner_id,
    fiscal_quarter,
    stage,
    cast(count(*) as integer)                                        as open_opportunities,
    cast(coalesce(sum(amount_usd), 0) as double)                     as pipeline_usd,
    cast(count(*) filter (where amount_usd is null) as integer)      as missing_amount_count
from {{ ref('int_opportunities__enriched') }}
where not is_closed
group by 1, 2, 3, 4
