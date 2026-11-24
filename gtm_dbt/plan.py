"""Turns triaged issues into a reviewable change plan (change_plan.json).

Every proposed change is a file to review, never an action: seed rows to add, a code diff for a staging
model, a task list for the CRM admin or the data engineer, a publication hold. Changes that alter reported
numbers or code are held and need a named approver to list them explicitly. Values only a person can know
(an FX rate, a canonical stage nobody can infer) are left as required human input; the agent never
invents them. The plan has no timestamps, so the same inputs always give the same SHA-256.
"""
from __future__ import annotations

import csv
import difflib
import re
from pathlib import Path

from .util import canonical_json, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_STAGES = ["Discovery", "Qualified", "Demo", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]


def project_hash(project_dir) -> str:
    h = []
    for p in sorted(Path(project_dir).rglob("*")):
        if p.is_file() and not any(part in ("target", "logs", "dbt_packages") for part in p.relative_to(project_dir).parts) \
                and p.suffix in (".sql", ".yml", ".csv", ".md"):
            h.append(str(p.relative_to(project_dir)) + ":" + sha256_bytes(p.read_bytes()))
    return sha256_bytes("\n".join(h).encode())


def stage_attrs(project_dir) -> dict:
    out = {}
    with open(Path(project_dir) / "seeds" / "stage_map.csv", newline="") as f:
        for r in csv.DictReader(f):
            out[r["stage"]] = {"stage_order": int(r["stage_order"]), "is_closed": r["is_closed"], "is_won": r["is_won"]}
    return out


def _staging_file(project_dir, root_name: str) -> Path | None:
    src, _, table = root_name.partition(".")
    p = Path(project_dir) / "models" / "staging" / src / f"stg_{src}__{table}.sql"
    return p if p.exists() else None


def _drift_files(project_dir, root_name: str) -> list[Path]:
    src, _, table = root_name.partition(".")
    files = [f for f in [_staging_file(project_dir, root_name)] if f]
    for snap in sorted((Path(project_dir) / "snapshots").glob("*.yml")):
        if f"source('{src}', '{table}')" in snap.read_text():
            files.append(snap)
    return files


def _ids(issue: dict) -> list[str]:
    ids = []
    for s in issue["symptoms"] + issue.get("folded", []):
        for r in s.get("evidence", []):
            for k in ("opportunity_id", "contact_id", "touch_id", "history_id", "owner_id", "unique_field", "id"):
                if r.get(k) and str(r[k]) not in ids and not str(r[k]).startswith("[quarantined"):
                    ids.append(str(r[k]))
                    break
    return ids[:20]


def change_for(issue: dict, n: int, project_dir) -> dict:
    cid = f"CHG-{n:02d}"
    cat, ex, root = issue["category"], issue.get("extra", {}), issue["root_name"]
    base = {"change_id": cid, "issue_id": issue["issue_id"], "type": issue["fix_type"], "target": root,
            "held": True, "requires_human_input": [], "patch": None}
    if cat == "stale_source":
        return {**base, "held": False, "type": "connector_check",
                "action": f"Check the connector sync for {root} ({ex.get('age', '')}). Do not publish downstream exposures until a fresh load lands, then re-run dbt."}
    if cat == "schema_drift":
        missing, cand = ex.get("missing_column"), ex.get("candidate_column")
        files = _drift_files(project_dir, root)
        if files and missing and cand:
            patches, diff = [], ""
            for f in files:
                edits = []
                for line in f.read_text().splitlines():
                    if re.search(rf"\b{re.escape(missing)}\b", line) and not line.strip().startswith("--"):
                        edits.append({"old": line, "new": re.sub(rf"\b{re.escape(missing)}\b", cand, line)})
                if edits:
                    rel = str(f.relative_to(project_dir))
                    patches.append({"file": rel, "edits": edits})
                    diff += "".join(difflib.unified_diff([e["old"] + "\n" for e in edits], [e["new"] + "\n" for e in edits],
                                                         f"a/dbt/{rel}", f"b/dbt/{rel}"))
            return {**base, "patch": {"kind": "code", "files": patches, "diff": diff},
                    "action": f"Source column '{missing}' is gone from {root}; '{cand}' is the closest raw column. Review the diff (staging model and any snapshot on this source), confirm with the CRM admin that the field was renamed, then merge."}
        return {**base, "requires_human_input": ["column_name"],
                "action": f"Source column '{missing}' is gone from {root} and no close match exists. Ask the CRM admin what replaced it."}
    if cat == "unmapped_stage":
        attrs = stage_attrs(project_dir)
        rows, need = [], []
        for raw, stage in sorted((ex.get("proposed_mappings") or {}).items()):
            if stage:
                rows.append({"raw_stage": raw, "stage": stage, **{k: str(v) for k, v in attrs[stage].items()}})
            else:
                rows.append({"raw_stage": raw, "stage": None})
                need.append(f"stage:{raw}")
        return {**base, "requires_human_input": need, "patch": {"kind": "seed_rows", "seed": "stage_map", "rows": rows},
                "action": "New CRM stage label(s) are not mapped. Confirm the proposed canonical stage (or choose one) so funnel and velocity stay comparable."}
    if cat == "missing_fx_rate":
        curr = ex.get("unmapped_values") or []
        return {**base, "requires_human_input": [f"rate_to_usd:{c}" for c in curr],
                "patch": {"kind": "seed_rows", "seed": "fx_rates", "rows": [{"currency": c, "rate_to_usd": None, "rate_note": "supplied by approver"} for c in curr]},
                "action": f"Currency {', '.join(curr) or '(see evidence)'} has no plan rate, so those deals drop out of USD pipeline. Finance supplies the rate; the agent never guesses one."}
    if cat == "duplicate_keys":
        prof = ex.get("duplicate_profile") or {}
        how = ("identical rows: a connector re-sync landed the same record twice. Ask data engineering to dedupe at the connector or switch the table to merge mode."
               if prof.get("conflicting", 1) == 0 else
               "conflicting rows share an id. Investigate in the CRM before any dedupe rule is written; picking a row silently would change pipeline.")
        return {**base, "action": f"{prof.get('duplicate_ids', '?')} duplicate id(s) in {root} ({how})",
                "record_ids": prof.get("sample_ids", [])}
    if cat in ("null_values", "orphan_reference", "unexpected_value", "invalid_amount"):
        return {**base, "held": False, "type": "crm_fix_task", "record_ids": _ids(issue),
                "action": f"CRM admin task: fix {cat.replace('_', ' ')} on {root} for the listed records, then re-run dbt."}
    if cat in ("timestamp_format_drift", "timezone_or_date_drift"):
        return {**base, "action": f"Dates in {root} no longer parse or land in the future. Check the export format and timezone setting before changing parse_ts()."}
    if cat == "metric_shift":
        return {**base, "action": "Numbers moved beyond the accepted range with no failing test. Review the drivers before anyone reads the dashboard.",
                "drivers": ex.get("driver_counts", {})}
    if cat == "contract_breach":
        return {**base, "action": f"{root} no longer matches its contract. Revert, or ship the change as a new model version with consumers told."}
    if cat == "dbt_invocation_failed":
        return {**base, "held": False, "type": "rerun_dbt", "action": "dbt did not finish; nothing was triaged. Fix the run and re-run the agent."}
    return {**base, "action": f"Human review: {cat.replace('_', ' ')} on {root}."}


def build_plan(issues: list, gate: dict, inputs: dict, project_dir) -> dict:
    changes = [change_for(i, n, project_dir) for n, i in enumerate(issues, 1)]
    if gate["hold"]:
        changes.append({"change_id": f"CHG-{len(changes) + 1:02d}", "issue_id": ",".join(gate["because"]), "type": "publication_hold",
                        "target": ",".join(gate["exposures"]), "held": False, "requires_human_input": [], "patch": None,
                        "action": f"Hold {', '.join(gate['exposures'])} until {', '.join(gate['because'])} are resolved."})
    return {"plan_version": 1, "inputs": inputs, "publication_gate": gate,
            "issues": [{k: i[k] for k in ("issue_id", "category", "root_name", "status", "severity", "fix_type", "blast_radius")}
                       | {"symptom_count": len(i["symptoms"]) + len(i.get("folded", []))} for i in issues],
            "changes": changes}


def plan_bytes(plan: dict) -> bytes:
    return (canonical_json(plan) + "\n").encode()
