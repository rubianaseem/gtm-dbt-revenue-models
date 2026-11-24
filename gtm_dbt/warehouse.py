"""Read-only queries against the local DuckDB warehouse: raw columns, duplicate profiles, key metrics."""
from __future__ import annotations

from pathlib import Path


def _con(db_path):
    import duckdb
    return duckdb.connect(str(db_path), read_only=True)


def raw_relation(source_node: str) -> str | None:
    """source.gtm_revenue.salesforce.opportunities -> raw_salesforce.opportunities"""
    parts = (source_node or "").split(".")
    if len(parts) != 4 or parts[0] != "source":
        return None
    return f"raw_{parts[2]}.{parts[3]}"


def raw_columns(db_path, source_node: str) -> list[str]:
    rel = raw_relation(source_node)
    if not rel or not Path(db_path).exists():
        return []
    schema, table = rel.split(".")
    con = _con(db_path)
    try:
        return [r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_schema=? and table_name=? order by ordinal_position",
            [schema, table]).fetchall()]
    finally:
        con.close()


def duplicate_profile(db_path, source_node: str) -> dict | None:
    rel = raw_relation(source_node)
    cols = [c for c in raw_columns(db_path, source_node) if c != "_fivetran_synced"]
    if not rel or "id" not in cols:
        return None
    con = _con(db_path)
    try:
        concat = " || '|' || ".join(f"coalesce(cast({c} as varchar),'')" for c in cols)
        rows = con.execute(
            f"select id, count(*) n, count(distinct {concat}) variants from {rel} group by id having count(*) > 1 order by id"
        ).fetchall()
    finally:
        con.close()
    return {"duplicate_ids": len(rows), "identical": sum(1 for r in rows if r[2] == 1),
            "conflicting": sum(1 for r in rows if r[2] > 1), "sample_ids": [r[0] for r in rows[:8]]}


def key_metrics(db_path) -> dict | None:
    try:
        con = _con(db_path)
    except Exception:
        return None
    try:
        q = lambda s: con.execute(s).fetchone()[0]
        return {
            "open_pipeline_usd": round(float(q("select coalesce(sum(pipeline_usd),0) from marts.fct_pipeline_snapshot")), 2),
            "open_opportunities": int(q("select coalesce(sum(open_opportunities),0) from marts.fct_pipeline_snapshot")),
            "closed_won_usd": round(float(q("select coalesce(sum(amount_usd),0) from intermediate.int_opportunities__enriched where is_won")), 2),
            "attributed_share": round(float(q("select avg(case when attribution_status='campaign' then 1.0 else 0 end) from marts.fct_lead_to_opportunity_attribution") or 0), 4),
            "people": int(q("select count(*) from intermediate.int_contacts__deduped")),
        }
    except Exception:
        return None
    finally:
        con.close()


def opportunity_amounts(db_path) -> dict:
    con = _con(db_path)
    try:
        out = {}
        for oid, amt in con.execute("select opportunity_id, amount_usd from intermediate.int_opportunities__enriched order by 1").fetchall():
            out.setdefault(oid, []).append(None if amt is None else round(float(amt), 2))
        return out
    except Exception:
        return {}
    finally:
        con.close()
