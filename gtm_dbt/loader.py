"""Stand-in for the connector (Fivetran/Airbyte): lands raw CSVs in DuckDB raw_* schemas, all columns as text,
plus a _fivetran_synced timestamp that dbt source freshness reads.

In production this file disappears: the connector writes raw_hubspot.* and raw_salesforce.* in Snowflake or
BigQuery and dbt reads them through sources. Nothing here talks to a CRM.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

TABLES = {
    "raw_hubspot": ["contacts", "companies", "campaigns", "touches"],
    "raw_salesforce": ["users", "opportunities", "opportunity_history", "tasks"],
}


def load_raw(raw_dir, db_path, now: datetime | None = None, sync_lag_hours: dict | None = None) -> dict:
    """Load every raw CSV. sync_lag_hours maps 'raw_salesforce.opportunities' -> hours since last sync."""
    import duckdb  # installed with dbt-duckdb

    raw_dir, db_path = Path(raw_dir), Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    lag = {"default": 1.0, **(sync_lag_hours or {})}
    counts = {}
    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET TimeZone='UTC'")
        for schema, tables in TABLES.items():
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            prefix = schema.replace("raw_", "")
            for t in tables:
                f = raw_dir / f"{prefix}__{t}.csv"
                synced = now - timedelta(hours=lag.get(f"{schema}.{t}", lag["default"]))
                con.execute(
                    f"CREATE OR REPLACE TABLE {schema}.{t} AS "
                    f"SELECT *, CAST(? AS TIMESTAMP) AS _fivetran_synced "
                    f"FROM read_csv(?, header=true, all_varchar=true, quote='\"')",
                    [synced.replace(tzinfo=None), str(f)],
                )
                counts[f"{schema}.{t}"] = con.execute(f"SELECT count(*) FROM {schema}.{t}").fetchone()[0]
    finally:
        con.close()
    return counts
