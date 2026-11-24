"""Reads dbt artifacts (manifest.json, run_results.json, sources.json) into flat findings.

A finding is one node that did not pass: a failing or warning data test, an errored model, seed or
snapshot, a failing unit test, or a stale source. Failing-row evidence is read from the
store_failures tables in DuckDB and sanitised before anything else sees it.
"""
from __future__ import annotations

import json
from pathlib import Path

from .untrusted import screen

NOT_PASS = {"fail", "warn", "error", "runtime error"}
EVIDENCE_ROWS = 5


class ArtifactError(Exception):
    pass


def load_json(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ArtifactError(f"missing artifact {Path(path).name}")
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"unreadable artifact {Path(path).name}: {exc.msg}")


def sanitise_row(row: dict, quarantine: list, record_hint: str = "") -> dict:
    """Drop *_untrusted columns, screen every other string, keep ids and numbers."""
    out = {}
    for k, v in row.items():
        if k.endswith("_untrusted") or k in ("notes", "description"):
            if v:
                hits = screen(str(v))
                if hits:
                    quarantine.append({"record": record_hint or row.get("opportunity_id") or row.get("contact_id"),
                                       "column": k, "patterns": hits})
            continue  # free text never leaves this function
        if isinstance(v, str):
            hits = screen(v)
            if hits:
                quarantine.append({"record": record_hint, "column": k, "patterns": hits})
                out[k] = f"[quarantined: {','.join(hits)}]"
                continue
            out[k] = v[:120]
        else:
            out[k] = v if isinstance(v, (int, float, bool)) or v is None else str(v)
    return out


def fetch_failing_rows(db_path, relation: str | None, quarantine: list) -> list[dict]:
    if not relation or not db_path:
        return []
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            cur = con.execute(f"select * from {relation} limit {EVIDENCE_ROWS}")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:
        return []
    return [sanitise_row(r, quarantine) for r in rows]


def parse(build_dir, freshness_dir=None, db_path=None) -> dict:
    build_dir = Path(build_dir)
    manifest = load_json(build_dir / "manifest.json")
    rr = load_json(build_dir / "run_results.json")
    if "results" not in rr or "nodes" not in manifest:
        raise ArtifactError("artifact missing expected keys (results/nodes)")
    nodes = {**manifest.get("nodes", {}), **manifest.get("sources", {}), **manifest.get("unit_tests", {})}
    quarantine: list = []
    findings, counts = [], {}
    for r in rr["results"]:
        status = r.get("status")
        counts[status] = counts.get(status, 0) + 1
        if status not in NOT_PASS:
            continue
        uid = r["unique_id"]
        n = nodes.get(uid, {})
        tm = n.get("test_metadata") or {}
        rtype = n.get("resource_type") or uid.split(".")[0]
        attached = n.get("attached_node")
        if rtype == "test" and not attached:
            deps = [d for d in n.get("depends_on", {}).get("nodes", []) if d.startswith(("model.", "snapshot.", "seed."))]
            attached = deps[0] if deps else None
        kwargs = tm.get("kwargs", {}) or {}
        f = {
            "node_id": uid,
            "resource_type": rtype,
            "status": "warn" if status == "warn" else "error",  # fail (error-severity test), error, runtime error
            "raw_status": status,
            "failures": r.get("failures"),
            "message": (r.get("message") or "")[:600],
            "test_name": (tm.get("name") if tm else ("singular:" + n.get("name", "")) if rtype == "test" else None),
            "column": n.get("column_name") or kwargs.get("column_name"),
            "kwargs": {k: v for k, v in kwargs.items() if k not in ("model", "column_name")},
            "attached_node": attached,
            "severity": (n.get("config") or {}).get("severity", "ERROR").upper() if rtype == "test" else "ERROR",
            "relation": r.get("relation_name") if rtype == "test" else None,
            "compiled_code": (r.get("compiled_code") or "")[:4000] if rtype in ("model", "snapshot") else None,
        }
        f["evidence"] = fetch_failing_rows(db_path, f["relation"], quarantine) if rtype == "test" else []
        findings.append(f)
    freshness = []
    if freshness_dir and (Path(freshness_dir) / "sources.json").exists():
        sj = load_json(Path(freshness_dir) / "sources.json")
        for s in sj.get("results", []):
            freshness.append({"node_id": s["unique_id"], "status": s.get("status"),
                              "max_loaded_at": s.get("max_loaded_at"),
                              "age_hours": round((s.get("max_loaded_at_time_ago_in_s") or 0) / 3600, 1),
                              "criteria": s.get("criteria")})
            if s.get("status") in ("warn", "error", "runtime error"):
                findings.append({"node_id": s["unique_id"], "resource_type": "source_freshness",
                                 "status": "error" if s["status"] != "warn" else "warn", "failures": None,
                                 "message": f"max loaded {round((s.get('max_loaded_at_time_ago_in_s') or 0)/3600,1)}h ago",
                                 "test_name": "freshness", "column": None, "kwargs": {}, "attached_node": s["unique_id"],
                                 "severity": "ERROR" if s["status"] != "warn" else "WARN", "relation": None,
                                 "compiled_code": None, "evidence": []})
    return {"manifest": manifest, "findings": findings, "status_counts": counts, "freshness": freshness,
            "quarantine": quarantine}
