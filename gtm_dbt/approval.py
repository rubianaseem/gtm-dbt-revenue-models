"""Enforced human approval bound to the SHA-256 of change_plan.json. Adapted from my revenue-signal-router.

Enforced in code (each rule has a unit test or failure-suite scenario):
  - The approver is a named human in config/approvers.json; agent, model, CI and service identities are refused.
  - The approver gives the full 64-character SHA-256 of change_plan.json; it must match the file on disk and
    the hash this run recorded in manifest.json. Editing the plan voids the approval.
  - Held changes (seed mappings, code diffs, dedupe decisions) are released only if listed explicitly by an
    approver allowed to approve held items. Required human inputs (FX rate, canonical stage) must be supplied
    and pass validation; the values are recorded in the hash-chained approvals log.
  - Approvals expire after approval_ttl_hours.
There is no auto-approve flag and no code path that releases a change without verify_approval() passing.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .audit import AuditLog, verify
from .plan import CANONICAL_STAGES
from .util import iso, parse_dt, read_json, sha256_file


class ApprovalError(Exception):
    pass


def is_agent(approver_id: str, blocked: list[str]) -> bool:
    toks = set(re.split(r"[^a-z0-9]+", (approver_id or "").lower()))
    return not (approver_id or "").strip() or bool(toks & {b.lower() for b in blocked})


def validate_value(key: str, value: str) -> str:
    kind, _, subject = key.partition(":")
    if kind == "rate_to_usd":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ApprovalError(f"{key}: '{value}' is not a number")
        if not 0 < v < 1000:
            raise ApprovalError(f"{key}: {v} is outside the plausible range (0, 1000)")
        return str(v)
    if kind == "stage":
        if value not in CANONICAL_STAGES:
            raise ApprovalError(f"{key}: '{value}' is not a canonical stage ({', '.join(CANONICAL_STAGES)})")
        return value
    if kind == "column_name":
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value or ""):
            raise ApprovalError(f"{key}: '{value}' is not a valid column name")
        return value
    raise ApprovalError(f"unknown input '{key}'")


def approve(run_dir, sha256: str, approver_id: str, now: datetime, approvers: dict,
            held: list[str] | None = None, values: dict | None = None) -> dict:
    run_dir = Path(run_dir)
    m = read_json(run_dir / "manifest.json")
    if is_agent(approver_id, approvers.get("blocked_identities", [])):
        raise ApprovalError(f"'{approver_id}' is an agent, model or service identity and can never approve")
    who = approvers.get("approvers", {}).get(approver_id)
    if not who:
        raise ApprovalError(f"unknown approver '{approver_id}'; approvers are named humans in config/approvers.json")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ApprovalError("approval needs the full 64-character SHA-256 printed by `python agent.py show`")
    current = sha256_file(run_dir / "change_plan.json")
    if sha256 != current:
        raise ApprovalError("hash does not match change_plan.json on disk; review the current plan and use its hash")
    if current != m["plan_sha256"]:
        raise ApprovalError("change_plan.json differs from what this run generated; re-run instead of editing outputs")
    plan = read_json(run_dir / "change_plan.json")
    by_id = {c["change_id"]: c for c in plan["changes"]}
    held = sorted(set(held or []))
    unknown = [h for h in held if h not in by_id or not by_id[h]["held"]]
    if unknown:
        raise ApprovalError(f"not held changes in this plan: {', '.join(unknown)}")
    if held and not who.get("may_approve_held"):
        raise ApprovalError(f"{who['name']} may approve the plan but not held changes")
    values = dict(values or {})
    clean = {}
    for h in held:
        for need in by_id[h]["requires_human_input"]:
            k = f"{h}.{need}"
            if k not in values:
                raise ApprovalError(f"{h} needs a human value for {need} (pass --value {k}=...)")
            clean[k] = validate_value(need, values.pop(k))
    if values:
        raise ApprovalError(f"values given for changes not being approved: {', '.join(sorted(values))}")
    log = AuditLog(run_dir / "approvals.jsonl", clock=lambda: now)
    return log.append({"event": "approved", "plan_sha256": sha256, "approver": approver_id, "approver_name": who["name"],
                       "run_id": m["run_id"], "held_changes_approved": held, "human_values": clean,
                       "expires_at": iso(now + timedelta(hours=approvers.get("approval_ttl_hours", 24)))})


def verify_approval(run_dir, now: datetime) -> dict:
    run_dir = Path(run_dir)
    m = read_json(run_dir / "manifest.json")
    ap = run_dir / "approvals.jsonl"
    if not ap.exists():
        raise ApprovalError("not approved: run `python agent.py approve` with a named approver and the plan hash")
    ok, why = verify(ap)
    if not ok:
        raise ApprovalError(f"approvals log failed verification: {why}")
    recs = [json.loads(x) for x in ap.read_text().splitlines() if x.strip()]
    mine = [r for r in recs if r.get("event") == "approved"]
    if not mine:
        raise ApprovalError("not approved")
    last = mine[-1]
    current = sha256_file(run_dir / "change_plan.json")
    if current != last["plan_sha256"] or current != m["plan_sha256"]:
        raise ApprovalError("plan changed after approval; approval is void")
    if now > parse_dt(last["expires_at"]):
        raise ApprovalError("approval expired; review and approve again")
    return last
