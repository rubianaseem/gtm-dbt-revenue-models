"""One agent run: land raw data -> dbt source freshness + dbt build -> parse artifacts -> metric guard ->
triage -> summaries -> change plan. Writes everything to a run folder and never changes anything else."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import artifacts, metric_guard, narrate, triage, warehouse
from .audit import AuditLog
from .dbt_runner import DBT_DIR, run_dbt
from .inject import apply as inject
from .loader import load_raw
from .plan import build_plan, plan_bytes, project_hash
from .util import read_json, sha256_bytes, write_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def raw_hash(raw_dir) -> str:
    return sha256_bytes("\n".join(f"{p.name}:{sha256_bytes(p.read_bytes())}" for p in sorted(Path(raw_dir).glob("*.csv"))).encode())


class Tracer:
    def __init__(self, path: Path):
        self.path = path
        self.spans = []

    def span(self, name: str, **attrs):
        tracer = self

        class _S:
            def __enter__(self_inner):
                self_inner.t0 = time.perf_counter()
                self_inner.attrs = dict(attrs)
                return self_inner

            def __exit__(self_inner, et, ev, tb):
                rec = {"span": name, "ms": round(1000 * (time.perf_counter() - self_inner.t0)),
                       "status": "error" if et else "ok", **self_inner.attrs}
                tracer.spans.append(rec)
                with open(tracer.path, "a") as fh:
                    fh.write(json.dumps(rec, default=str) + "\n")
                return False
        return _S()


def run(run_dir, raw_dir=None, mutations=None, as_of="2026-11-20", client=None, now=None,
        dbt_bin=None, baseline=None, known=None) -> dict:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("trace.jsonl",):
        (run_dir / stale).unlink(missing_ok=True)
    now = now or datetime.now(timezone.utc)
    tr = Tracer(run_dir / "trace.jsonl")
    raw_dir = Path(raw_dir or ROOT / "data" / "raw")
    with tr.span("inject", mutations=len(mutations or [])):
        inj = inject(raw_dir, run_dir / "raw_input", mutations or [], DBT_DIR, run_dir / "project")
    project_dir = inj["project_dir"] or DBT_DIR
    inputs = {"raw_sha256": raw_hash(run_dir / "raw_input"), "project_sha256": project_hash(project_dir), "as_of_date": as_of,
              "sync_lag_hours": inj["sync_lag_hours"],
              "metric_baseline_run": (baseline if baseline is not None else read_json(CONFIG / "metric_baseline.json")).get("run_id")}
    run_id = "run-" + sha256_bytes(json.dumps(inputs, sort_keys=True).encode())[:12]
    audit = AuditLog(run_dir / "audit.jsonl", clock=lambda: now)
    audit.append({"event": "run_started", "run_id": run_id, "inputs": inputs})
    db = run_dir / "warehouse" / "gtm.duckdb"
    if db.exists():
        db.unlink()
    with tr.span("load_raw") as s:
        # freshness is measured by dbt against the real clock, so the connector stand-in uses it too
        s.attrs["rows"] = load_raw(run_dir / "raw_input", db, now=datetime.now(timezone.utc), sync_lag_hours=inj["sync_lag_hours"])
    with tr.span("dbt") as s:
        res = run_dbt(run_dir, db, project_dir=project_dir, as_of=as_of, dbt_bin=dbt_bin)
        s.attrs.update({k: res[k] for k in ("freshness_exit", "build_exit", "ok")})
    audit.append({"event": "dbt_finished", **{k: res[k] for k in ("freshness_exit", "build_exit", "ok", "error")}})

    quarantine, status_counts, guard = [], {}, {"status": "unavailable"}
    with tr.span("triage") as s:
        if res["ok"]:
            try:
                parsed = artifacts.parse(run_dir / "dbt_build", run_dir / "dbt_freshness", db)
            except artifacts.ArtifactError as exc:
                parsed, res = None, {**res, "ok": False, "error": str(exc)}
        if res["ok"]:
            quarantine, status_counts = parsed["quarantine"], parsed["status_counts"]
            guard = metric_guard.check(db, baseline if baseline is not None else read_json(CONFIG / "metric_baseline.json"),
                                       read_json(CONFIG / "metric_guard.json"))
            findings = list(parsed["findings"])
            mf = metric_guard.as_finding(guard)
            if mf:
                findings.append(mf)
            tri = triage.build_issues(findings, parsed["manifest"], known if known is not None else read_json(CONFIG / "known_issues.json"),
                                      today=date.fromisoformat(as_of),
                                      raw_columns_fn=lambda r: warehouse.raw_columns(db, r),
                                      dup_profile_fn=lambda r: warehouse.duplicate_profile(db, r))
            issues, acks = tri["issues"], tri["acknowledged"]
        else:  # fail closed
            issues = [{"issue_id": "ISS-01", "category": "dbt_invocation_failed", "root": None, "root_name": "dbt",
                       "status": "error", "fix_type": "rerun_dbt", "extra": {"error": res["error"]},
                       "symptoms": [{"node": "dbt", "node_id": "dbt", "status": "error", "failures": None, "test": None,
                                     "column": None, "evidence": []}], "folded": [], "severity": "high",
                       "blast_radius": {"models": [], "exposures": ["weekly_pipeline_review", "campaign_attribution_report"]}}]
            acks = []
        s.attrs.update({"issues": len(issues), "quarantined": len(quarantine)})
    for q in quarantine:
        audit.append({"event": "free_text_quarantined", "record": q["record"], "column": q["column"], "patterns": q["patterns"]})
    with tr.span("summaries") as s:
        summaries, mode = narrate.summarise(issues, client, log=audit.append)
        s.attrs["mode"] = mode
    gate = triage.publication_gate(issues)
    plan = build_plan(issues, gate, inputs, project_dir)
    pb = plan_bytes(plan)
    (run_dir / "change_plan.json").write_bytes(pb)
    plan_sha = sha256_bytes(pb)
    prev = run_dir / "manifest.json"
    if prev.exists():
        old_sha = read_json(prev).get("plan_sha256")
        if old_sha != plan_sha:  # a new plan voids earlier approvals and releases; keep them for the record
            arch, n = run_dir / f"superseded-{old_sha[:12]}", 1
            while arch.exists():
                n += 1
                arch = run_dir / f"superseded-{old_sha[:12]}-{n}"
            for name in ("approvals.jsonl", "released", "sandbox", "sandbox_verification.json"):
                if (run_dir / name).exists():
                    arch.mkdir(exist_ok=True)
                    (run_dir / name).rename(arch / name)
    report = {"run_id": run_id, "plan_sha256": plan_sha, "dbt": res, "status_counts": status_counts,
              "freshness": parsed["freshness"] if res["ok"] else [], "metric_guard": guard,
              "issues": issues, "acknowledged": acks, "summaries": summaries, "summary_mode": mode,
              "quarantined": quarantine, "publication_gate": gate}
    write_json(run_dir / "triage.json", report)
    write_json(run_dir / "manifest.json", {"run_id": run_id, "plan_sha256": plan_sha, "inputs": inputs,
                                           "project_dir": str(project_dir), "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    (run_dir / "report.md").write_text(render_report(report, plan))
    audit.append({"event": "plan_written", "plan_sha256": plan_sha, "issues": len(issues), "changes": len(plan["changes"]),
                  "publication_hold": gate["hold"], "summary_mode": mode})
    return {**report, "plan": plan, "project_dir": str(project_dir)}


def render_report(r: dict, plan: dict) -> str:
    L = [f"# dbt triage report ({r['run_id']})", "",
         f"dbt build: {r['status_counts'] or 'did not finish'}", f"Publication gate: {'HOLD ' + ', '.join(r['publication_gate']['exposures']) if r['publication_gate']['hold'] else 'clear'}",
         f"Metric guard: {r['metric_guard'].get('status')}", f"Summaries: {r['summary_mode']}", "", "## Issues", ""]
    for i in r["issues"]:
        L.append(f"- **{i['issue_id']} {i['category']}** at `{i['root_name']}` ({i['severity']}): {r['summaries'][i['issue_id']]}")
    if not r["issues"]:
        L.append("- none")
    L += ["", "## Accepted known issues (not raised)", ""] + [f"- {a['node']}: {a['failures']} row(s). {a['reason']} Owner {a['owner']}, expires {a['expires']}." for a in r["acknowledged"]]
    L += ["", "## Proposed changes (nothing happens until a named person approves the plan hash)", ""]
    for c in plan["changes"]:
        need = f" Needs human input: {', '.join(c['requires_human_input'])}." if c["requires_human_input"] else ""
        L.append(f"- {c['change_id']} [{c['type']}{', HELD' if c['held'] else ''}] {c['action']}{need}")
    if r["quarantined"]:
        L += ["", f"{len(r['quarantined'])} free-text value(s) quarantined (record ids and pattern ids only are in audit.jsonl)."]
    L += ["", f"Plan SHA-256: `{r['plan_sha256']}`", ""]
    return "\n".join(L)
