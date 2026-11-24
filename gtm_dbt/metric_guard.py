"""Metric-change guard: catches changes that pass every dbt test but move the numbers leadership reads.

Compares key metrics against the last human-accepted baseline (config/metric_baseline.json) and explains
any move beyond config/metric_guard.json thresholds with per-opportunity drivers: suspected unit errors
(amount jumped 20x or more), duplicate rows, new or removed opportunities.
"""
from __future__ import annotations

from .warehouse import key_metrics, opportunity_amounts

ROOT_SOURCE = "source.gtm_revenue.salesforce.opportunities"


def check(db_path, baseline: dict, thresholds: dict) -> dict:
    cur = key_metrics(db_path)
    if cur is None:
        return {"status": "unavailable", "metrics": None, "shifts": [], "drivers": []}
    base = baseline.get("metrics", {})
    shifts = []
    for k, limit in thresholds.items():
        b, c = base.get(k), cur.get(k)
        if b in (None, 0) or c is None:
            continue
        rel = (c - b) / abs(b)
        if abs(rel) > limit:
            shifts.append({"metric": k, "baseline": b, "current": c, "change_pct": round(100 * rel, 1), "limit_pct": round(100 * limit, 1)})
    drivers = []
    if shifts:
        now_amt, base_amt = opportunity_amounts(db_path), baseline.get("opportunity_amounts", {})
        for oid, vals in now_amt.items():
            b = base_amt.get(oid)
            if len(vals) > 1:
                drivers.append({"opportunity_id": oid, "kind": "duplicate_rows", "rows": len(vals)})
            elif b is None:
                drivers.append({"opportunity_id": oid, "kind": "new_opportunity", "amount_usd": vals[0]})
            elif vals[0] and b[0] and vals[0] / b[0] >= 20:
                drivers.append({"opportunity_id": oid, "kind": "unit_error_suspected", "baseline_usd": b[0], "current_usd": vals[0]})
        for oid in sorted(set(base_amt) - set(now_amt)):
            drivers.append({"opportunity_id": oid, "kind": "removed_opportunity"})
    return {"status": "shift" if shifts else "ok", "metrics": cur, "shifts": shifts, "drivers": drivers[:12],
            "driver_counts": _count(drivers)}


def _count(drivers):
    out = {}
    for d in drivers:
        out[d["kind"]] = out.get(d["kind"], 0) + 1
    return out


def as_finding(result: dict) -> dict | None:
    if result["status"] != "shift":
        return None
    msg = "; ".join(f"{s['metric']} {s['change_pct']:+}% vs accepted baseline (limit {s['limit_pct']}%)" for s in result["shifts"])
    return {"node_id": "metric_guard.pipeline", "resource_type": "metric_guard", "status": "error", "failures": len(result["shifts"]),
            "message": msg, "test_name": "metric_guard", "column": None, "kwargs": {}, "severity": "ERROR",
            "attached_node": "model.gtm_revenue.fct_pipeline_snapshot", "root": ROOT_SOURCE, "relation": None,
            "compiled_code": None, "evidence": result["drivers"][:5], "metric_shifts": result["shifts"],
            "driver_counts": result.get("driver_counts", {})}
