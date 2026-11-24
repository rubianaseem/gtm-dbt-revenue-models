"""Baseline: what a person does today with `dbt build` output alone ("read the red tests").

One ticket per non-passing node in run_results.json, categorised by the generic test name
(unique -> duplicate_keys, not_null -> null_values, relationships -> orphan_reference,
accepted_values -> unexpected_value; anything else -> unknown or model_error). Staging nodes are mapped to
their source so the baseline gets the same root normalisation as the agent. No source freshness (dbt build
does not run it), no metric comparison, no known-issue register, no folding of downstream symptoms.
Publication is held when dbt build exits non-zero.
"""
from __future__ import annotations

import json
from pathlib import Path

from gtm_dbt.triage import Lineage

MAP = {"unique": "duplicate_keys", "not_null": "null_values", "relationships": "orphan_reference",
       "accepted_values": "unexpected_value"}


def run(build_dir, build_exit: int) -> dict:
    build_dir = Path(build_dir)
    manifest = json.loads((build_dir / "manifest.json").read_text())
    rr = json.loads((build_dir / "run_results.json").read_text())
    lin = Lineage(manifest)
    nodes = {**manifest["nodes"], **manifest.get("unit_tests", {})}
    issues = []
    for r in rr["results"]:
        if r["status"] not in ("fail", "warn", "error"):
            continue
        n = nodes.get(r["unique_id"], {})
        tm = (n.get("test_metadata") or {}).get("name")
        if n.get("resource_type") in ("model", "snapshot", "seed"):
            cat, attached = "model_error", r["unique_id"]
        else:
            cat = MAP.get(tm, "unknown")
            attached = n.get("attached_node") or next((d for d in n.get("depends_on", {}).get("nodes", []) if d.startswith("model.")), r["unique_id"])
        root = lin.root_of({"resource_type": "test", "attached_node": attached, "node_id": r["unique_id"]})
        issues.append({"category": cat, "root_name": lin.name(root), "node": r["unique_id"]})
    return {"issues": issues, "hold": build_exit != 0}
