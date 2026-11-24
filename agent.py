"""dbt failure and metric-change triage agent.

  python agent.py run [--run-dir outputs/run/latest] [--scenario evals/scenarios_v1/dev.json#S03]
  python agent.py show
  python agent.py approve --approver rubia --sha256 <hash> [--held CHG-02,CHG-03] [--value CHG-03.rate_to_usd:AUD=0.66]
  python agent.py release [--verify-sandbox]
  python agent.py verify
  python agent.py accept-baseline --approver rubia

No API key needed. With ANTHROPIC_API_KEY set, Claude may re-word issue summaries only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from gtm_dbt import artifacts, pipeline
from gtm_dbt.approval import ApprovalError, approve, is_agent
from gtm_dbt.audit import AuditLog, verify
from gtm_dbt.dbt_runner import DBT_DIR, run_dbt
from gtm_dbt.llm import get_client
from gtm_dbt.release import release, verify_in_sandbox
from gtm_dbt.util import read_json, sha256_file, write_json
from gtm_dbt.warehouse import key_metrics, opportunity_amounts

ROOT = Path(__file__).resolve().parent
DEFAULT_RUN = ROOT / "outputs" / "run" / "latest"


def load_scenario(ref: str) -> list:
    path, _, sid = ref.partition("#")
    data = read_json(ROOT / path)
    for s in data["scenarios"]:
        if s["id"] == sid:
            return s["mutations"]
    raise SystemExit(f"scenario {sid} not found in {path}")


def cmd_run(a):
    muts = load_scenario(a.scenario) if a.scenario else []
    client = get_client()
    r = pipeline.run(a.run_dir, mutations=muts, client=client)
    print(f"run {r['run_id']}  dbt: {r['status_counts'] or r['dbt']['error']}  summaries: {r['summary_mode']}")
    for f in r["freshness"]:
        if f["status"] != "pass":
            print(f"  freshness {f['status']:5} {f['node_id'].split('.',2)[-1]} ({f['age_hours']}h since last load)")
    for i in r["issues"]:
        print(f"  {i['issue_id']} {i['severity']:6} {i['category']:24} {i['root_name']:34} symptoms {len(i['symptoms']) + len(i['folded'])}")
    for ack in r["acknowledged"]:
        print(f"  accepted (not raised): {ack['node'][:60]} ({ack['failures']} rows, expires {ack['expires']})")
    print(f"  publication gate: {'HOLD ' + ', '.join(r['publication_gate']['exposures']) if r['publication_gate']['hold'] else 'clear'}")
    print(f"  plan sha256: {r['plan_sha256']}  ({len(r['plan']['changes'])} proposed changes, {sum(c['held'] for c in r['plan']['changes'])} held)")
    print(f"  report: {Path(a.run_dir) / 'report.md'}")


def cmd_show(a):
    p = Path(a.run_dir)
    print((p / "report.md").read_text())
    print("sha256 of change_plan.json:", sha256_file(p / "change_plan.json"))


def _values(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k] = v
    return out


def cmd_approve(a):
    try:
        rec = approve(a.run_dir, a.sha256, a.approver, datetime.now(timezone.utc), read_json(ROOT / "config" / "approvers.json"),
                      held=[h for h in (a.held or "").split(",") if h], values=_values(a.value))
    except ApprovalError as exc:
        print("REFUSED:", exc)
        sys.exit(2)
    print(f"approved by {rec['approver_name']} (held: {', '.join(rec['held_changes_approved']) or 'none'}; expires {rec['expires_at']})")


def cmd_release(a):
    m = read_json(Path(a.run_dir) / "manifest.json")
    try:
        out = release(a.run_dir, datetime.now(timezone.utc), m["project_dir"])
    except ApprovalError as exc:
        print("REFUSED:", exc)
        sys.exit(2)
    print(json.dumps(out))
    if a.verify_sandbox:
        v = verify_in_sandbox(a.run_dir, m["project_dir"], run_dbt, artifacts.parse)
        write_json(Path(a.run_dir) / "sandbox_verification.json", v)
        print("sandbox:", json.dumps({k: v[k] for k in v if k != "status_counts"}))


def cmd_verify(a):
    for f in ("audit.jsonl", "approvals.jsonl"):
        p = Path(a.run_dir) / f
        if p.exists():
            print(f, verify(p))


def cmd_accept_baseline(a):
    appr = read_json(ROOT / "config" / "approvers.json")
    if is_agent(a.approver, appr["blocked_identities"]) or a.approver not in appr["approvers"]:
        print("REFUSED: only a named human approver can accept a metric baseline")
        sys.exit(2)
    t = read_json(Path(a.run_dir) / "triage.json")
    if any(i["status"] == "error" for i in t["issues"]):
        print("REFUSED: this run has error-level issues; a baseline must come from a clean run")
        sys.exit(2)
    db = Path(a.run_dir) / "warehouse" / "gtm.duckdb"
    write_json(ROOT / "config" / "metric_baseline.json", {"accepted_by": a.approver, "run_id": t["run_id"],
                                                          "metrics": key_metrics(db), "opportunity_amounts": opportunity_amounts(db)})
    print("baseline accepted from", t["run_id"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--scenario"); r.set_defaults(fn=cmd_run)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    p = sub.add_parser("approve"); p.add_argument("--approver", required=True); p.add_argument("--sha256", required=True)
    p.add_argument("--held"); p.add_argument("--value", action="append"); p.set_defaults(fn=cmd_approve)
    rl = sub.add_parser("release"); rl.add_argument("--verify-sandbox", action="store_true"); rl.set_defaults(fn=cmd_release)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    b = sub.add_parser("accept-baseline"); b.add_argument("--approver", required=True); b.set_defaults(fn=cmd_accept_baseline)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
