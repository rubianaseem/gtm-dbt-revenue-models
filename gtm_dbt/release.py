"""Releases approved changes as reviewable files, optionally proving seed and code fixes in a sandbox.

"Release" never touches the CRM, the warehouse the business reads, or this repo's dbt/ folder. It writes:
  released/patches/seeds/<seed>.csv   rows to add, completed with the approver's values
  released/patches/<model>.diff       code diffs for a pull request
  released/tasks.csv                  CRM-admin and data-engineering tasks (record ids only)
  released/publication_hold.json      exposures to hold
A ledger (released/ledger.jsonl) records each change as it is written, so a crash mid-release resumes
without duplicating anything and a second release is a no-op.
"""
from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

from .approval import ApprovalError, verify_approval
from .audit import AuditLog
from .plan import project_hash, stage_attrs
from .util import read_json, sha256_file, write_json


def _ledger(path: Path) -> set:
    if not path.exists():
        return set()
    return {json.loads(x)["key"] for x in path.read_text().splitlines() if x.strip()}


def completed_rows(change: dict, values: dict, project_dir) -> list[dict]:
    rows, cid = [], change["change_id"]
    attrs = stage_attrs(project_dir) if change["patch"]["seed"] == "stage_map" else {}
    for r in change["patch"]["rows"]:
        r = dict(r)
        if change["patch"]["seed"] == "fx_rates":
            r["rate_to_usd"] = values[f"{cid}.rate_to_usd:{r['currency']}"]
        elif r.get("stage") is None:
            r["stage"] = values[f"{cid}.stage:{r['raw_stage']}"]
            r.update({k: str(v) for k, v in attrs[r["stage"]].items()})
        rows.append(r)
    return rows


def release(run_dir, now: datetime, project_dir, crash_after: int | None = None) -> dict:
    run_dir = Path(run_dir)
    appr = verify_approval(run_dir, now)
    m = read_json(run_dir / "manifest.json")
    if project_hash(project_dir) != m["inputs"]["project_sha256"]:
        raise ApprovalError("dbt project changed since this plan was made; re-run the agent and approve the new plan")
    plan = read_json(run_dir / "change_plan.json")
    out = run_dir / "released"
    out.mkdir(exist_ok=True)
    ledger_path = out / "ledger.jsonl"
    done = _ledger(ledger_path)
    audit = AuditLog(run_dir / "audit.jsonl", clock=lambda: now)
    written, skipped, withheld = [], [], []
    approved_held = set(appr["held_changes_approved"])
    for c in plan["changes"]:
        key = f"{m['plan_sha256'][:16]}:{c['change_id']}"
        if c["held"] and c["change_id"] not in approved_held:
            withheld.append(c["change_id"])
            continue
        if key in done:
            skipped.append(c["change_id"])
            continue
        if crash_after is not None and len(written) >= crash_after:
            raise RuntimeError("simulated crash during release")
        p = c.get("patch") or {}
        if p.get("kind") == "seed_rows":
            rows = completed_rows(c, appr["human_values"], project_dir)
            f = out / "patches" / "seeds" / f"{p['seed']}.csv"
            f.parent.mkdir(parents=True, exist_ok=True)
            new = not f.exists()
            header = (Path(project_dir) / "seeds" / f"{p['seed']}.csv").read_text().splitlines()[0].split(",")
            with open(f, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n", extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerows(rows)
        elif p.get("kind") == "code":
            f = out / "patches" / (Path(p["files"][0]["file"]).stem + ".diff")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(p["diff"])
        elif c["type"] == "publication_hold":
            write_json(out / "publication_hold.json", {"exposures": c["target"].split(","), "because": c["issue_id"],
                                                       "plan_sha256": m["plan_sha256"]})
        else:
            f = out / "tasks.csv"
            new = not f.exists()
            with open(f, "a", newline="") as fh:
                w = csv.writer(fh, lineterminator="\n")
                if new:
                    w.writerow(["change_id", "issue_id", "type", "target", "action", "record_ids"])
                w.writerow([c["change_id"], c["issue_id"], c["type"], c["target"], c["action"], " ".join(c.get("record_ids", []))])
        with open(ledger_path, "a") as fh:
            fh.write(json.dumps({"key": key, "change_id": c["change_id"]}) + "\n")
        written.append(c["change_id"])
        audit.append({"event": "change_released", "change_id": c["change_id"], "type": c["type"], "approver": appr["approver"]})
    return {"written": written, "already_released": skipped, "withheld_not_approved": withheld}


def verify_in_sandbox(run_dir, project_dir, run_dbt_fn, parse_fn) -> dict:
    """Copy the dbt project and the run's warehouse, apply released seed rows and code diffs, rebuild,
    and report which symptom tests now pass. The repo's dbt/ folder and the run warehouse are untouched."""
    run_dir = Path(run_dir)
    sb = run_dir / "sandbox"
    if sb.exists():
        shutil.rmtree(sb)  # sandbox is a rebuildable scratch copy inside this run folder
    proj = sb / "dbt"
    shutil.copytree(project_dir, proj, ignore=shutil.ignore_patterns("target", "logs", "dbt_packages"))
    shutil.copy(run_dir / "warehouse" / "gtm.duckdb", sb / "gtm.duckdb")
    rel = run_dir / "released" / "patches"
    applied = []
    for f in sorted((rel / "seeds").glob("*.csv")) if (rel / "seeds").exists() else []:
        target = proj / "seeds" / f.name
        cols = target.read_text().splitlines()[0].split(",")
        with open(f, newline="") as src, open(target, "a", newline="") as dst:
            w = csv.DictWriter(dst, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
            for row in csv.DictReader(src):
                w.writerow(row)
        applied.append(f"seed:{f.stem}")
    plan = read_json(run_dir / "change_plan.json")
    released_ids = {json.loads(x)["change_id"] for x in (run_dir / "released" / "ledger.jsonl").read_text().splitlines() if x.strip()}
    for c in plan["changes"]:
        p = c.get("patch") or {}
        if p.get("kind") == "code" and c["change_id"] in released_ids:
            for fp in p["files"]:
                target = proj / fp["file"]
                text = target.read_text()
                for e in fp["edits"]:
                    text = text.replace(e["old"], e["new"])
                target.write_text(text)
                applied.append(f"code:{fp['file']}")
    res = run_dbt_fn(sb / "run", sb / "gtm.duckdb", project_dir=proj)
    if not res["ok"]:
        return {"applied": applied, "ok": False, "error": res["error"]}
    parsed = parse_fn(sb / "run" / "dbt_build", None, sb / "gtm.duckdb")
    still = {f["node_id"] for f in parsed["findings"] if f["status"] == "error"}
    return {"applied": applied, "ok": True, "still_failing_error_nodes": sorted(still),
            "status_counts": parsed["status_counts"], "repo_project_unchanged": True}
