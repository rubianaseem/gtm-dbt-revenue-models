"""End-to-end demo with no API key: a clean run, then a synthetic Monday-morning incident triaged, approved by
a named human, released as reviewable files, proven in a sandbox rebuild, and re-released as a no-op.

  python run_demo.py      (about 40 seconds; writes outputs/demo_transcript.txt and outputs/demo/)
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from gtm_dbt import artifacts, pipeline
from gtm_dbt.approval import ApprovalError, approve
from gtm_dbt.audit import verify
from gtm_dbt.dbt_runner import run_dbt
from gtm_dbt.release import release, verify_in_sandbox
from gtm_dbt.util import read_json, write_json

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
APPROVERS = read_json(ROOT / "config" / "approvers.json")


def show_run(title, r):
    print(f"\n== {title}")
    print(f"dbt build: {r['status_counts']}   (exit {r['dbt']['build_exit']}; source freshness exit {r['dbt']['freshness_exit']})")
    for f in r["freshness"]:
        if f["status"] != "pass":
            print(f"  freshness {f['status']}: {f['node_id'].split('.', 2)[-1]} last loaded {f['age_hours']}h ago")
    for a in r["acknowledged"]:
        print(f"  accepted known issue (not raised): {a['node'][:58]} ({a['failures']} rows, owner {a['owner']}, expires {a['expires']})")
    for i in r["issues"]:
        print(f"  {i['issue_id']} {i['severity']:6} {i['category']:22} {i['root_name']:32} symptoms {len(i['symptoms']) + len(i['folded'])}")
    print(f"  metric guard: {r['metric_guard']['status']}   publication gate: "
          f"{'HOLD ' + ', '.join(r['publication_gate']['exposures']) if r['publication_gate']['hold'] else 'clear'}")
    print(f"  free-text values quarantined: {len(r['quarantined'])}   summaries: {r['summary_mode']}")
    print(f"  plan sha256 {r['plan_sha256'][:16]}...  changes {len(r['plan']['changes'])} ({sum(c['held'] for c in r['plan']['changes'])} held)")


def main():
    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            buf.write(s)
            return len(s)

    with redirect_stdout(Tee()):
        demo_dir = OUT / "demo_run"
        if demo_dir.exists():
            shutil.rmtree(demo_dir)  # rebuildable demo scratch folder
        r0 = pipeline.run(demo_dir / "clean")
        show_run("1. Clean run (synthetic HubSpot + Salesforce export)", r0)

        incident = read_json(ROOT / "config" / "demo_incident.json")
        r = pipeline.run(demo_dir / "incident", mutations=incident["mutations"])
        show_run(f"2. {incident['title']}", r)
        print("\n== 3. Issue summaries (template mode; Claude only re-words these when a key is set)")
        for iid, s in r["summaries"].items():
            print(f"  {iid}: {s[:230]}")
        print("\n== 4. Proposed changes")
        for c in r["plan"]["changes"]:
            need = f"  needs: {', '.join(c['requires_human_input'])}" if c["requires_human_input"] else ""
            print(f"  {c['change_id']} {c['type']:22}{' HELD' if c['held'] else '     '} {c['target'][:40]}{need}")

        run_dir, sha, now = demo_dir / "incident", r["plan_sha256"], datetime.now(timezone.utc)
        print("\n== 5. Approval")
        try:
            approve(run_dir, sha, "claude-agent", now, APPROVERS)
        except ApprovalError as exc:
            print(f"  approve as claude-agent: REFUSED ({exc})")
        seed_changes = [c for c in r["plan"]["changes"] if c["held"] and (c.get("patch") or {}).get("kind") == "seed_rows"]
        try:
            approve(run_dir, sha, "rubia", now, APPROVERS, held=[c["change_id"] for c in seed_changes])
        except ApprovalError as exc:
            print(f"  approve held seed changes with no values: REFUSED ({exc})")
        values = {}
        for c in seed_changes:
            for n in c["requires_human_input"]:
                values[f"{c['change_id']}.{n}"] = "0.66" if n.startswith("rate_to_usd") else "Negotiation"
        rec = approve(run_dir, sha, "rubia", now, APPROVERS, held=[c["change_id"] for c in seed_changes], values=values)
        print(f"  approve as rubia, held {rec['held_changes_approved']}, values {rec['human_values']} (demo values, synthetic): APPROVED")
        print("\n== 6. Release (files only) and sandbox proof")
        out = release(run_dir, now, r["project_dir"])
        print(f"  released {out['written']}; withheld (held, not approved) {out['withheld_not_approved']}")
        v = verify_in_sandbox(run_dir, r["project_dir"], run_dbt, artifacts.parse)
        write_json(run_dir / "sandbox_verification.json", v)
        print(f"  sandbox applied {v['applied']}")
        print(f"  sandbox rebuild: {v['status_counts']}; error nodes still failing: {len(v['still_failing_error_nodes'])}")
        for n in v["still_failing_error_nodes"]:
            print(f"    still failing (needs the withheld or human fixes): {n.split('.')[-2] if n.count('.') > 2 else n}")
        again = release(run_dir, now, r["project_dir"])
        print(f"  release again: wrote {len(again['written'])} (already released {len(again['already_released'])})")
        print("\n== 7. Audit")
        for f in ("audit.jsonl", "approvals.jsonl"):
            print(f"  {f}: {verify(run_dir / f)}")
        print("  writes to CRM or the business warehouse: none (release writes files under the run folder only)")

    (OUT / "demo_transcript.txt").write_text(buf.getvalue())
    keep = OUT / "demo"
    if keep.exists():
        shutil.rmtree(keep)  # committed copy of the latest demo, regenerated each run
    keep.mkdir(parents=True)
    for f in ("report.md", "change_plan.json", "triage.json", "audit.jsonl", "approvals.jsonl", "trace.jsonl", "sandbox_verification.json"):
        shutil.copy(run_dir / f, keep / f)
    shutil.copytree(run_dir / "released", keep / "released")


if __name__ == "__main__":
    main()
