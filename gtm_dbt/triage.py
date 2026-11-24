"""Deterministic triage: dbt findings -> root-cause issues with category, severity, blast radius and a typed fix.

Rules, in order, live in classify(). Findings that are downstream symptoms of an error-level issue at an
upstream root are folded into that issue instead of becoming separate tickets. Accepted known issues
(config/known_issues.json) are listed but not raised. No model is involved here: an optional model may
only re-word the summary later (narrate.py), never the category, root, severity or fix.
"""
from __future__ import annotations

import difflib
import re
from datetime import date

FIX_TYPES = {
    "stale_source": "connector_check",
    "schema_drift": "staging_column_remap",
    "type_drift": "staging_cast_fix",
    "contract_breach": "revert_or_version_model",
    "duplicate_keys": "duplicate_investigation",
    "null_values": "crm_fix_task",
    "timestamp_format_drift": "staging_parse_fix",
    "unmapped_stage": "seed_row_add",
    "missing_fx_rate": "seed_row_add",
    "orphan_reference": "crm_fix_task",
    "timezone_or_date_drift": "staging_parse_fix",
    "metric_reconciliation": "logic_review",
    "metric_shift": "metric_shift_review",
    "unexpected_value": "crm_fix_task",
    "invalid_amount": "crm_fix_task",
    "logic_regression": "revert_or_version_model",
    "dbt_invocation_failed": "rerun_dbt",
    "unknown": "human_review",
}
# categories that can be a downstream symptom of an upstream error-level issue
FOLDABLE = {"null_values", "metric_reconciliation", "metric_shift", "orphan_reference", "unexpected_value",
            "missing_fx_rate", "unknown", "duplicate_keys", "timezone_or_date_drift"}
STAGE_RULES = [("won", "Closed Won"), ("lost", "Closed Lost"), ("negotiat", "Negotiation"), ("contract", "Negotiation"),
               ("propos", "Proposal"), ("quote", "Proposal"), ("demo", "Demo"), ("qualif", "Qualified"),
               ("discover", "Discovery")]


class Lineage:
    def __init__(self, manifest: dict):
        self.parents = manifest.get("parent_map", {})
        self.children = manifest.get("child_map", {})
        self.nodes = {**manifest.get("nodes", {}), **manifest.get("sources", {}), **manifest.get("exposures", {})}

    def ancestors(self, node: str) -> set:
        seen, stack = set(), [node]
        while stack:
            for p in self.parents.get(stack.pop(), []):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    def descendants(self, node: str) -> set:
        seen, stack = set(), [node]
        while stack:
            for c in self.children.get(stack.pop(), []):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    def name(self, node: str | None) -> str:
        if not node:
            return ""
        n = self.nodes.get(node, {})
        if node.startswith("source."):
            return f"{n.get('source_name', node.split('.')[-2])}.{n.get('name', node.split('.')[-1])}"
        return n.get("name", node.split(".")[-1])

    def is_staging(self, node: str | None) -> bool:
        return bool(node) and self.name(node).startswith("stg_")

    def root_of(self, f: dict) -> str | None:
        if f["resource_type"] == "source_freshness":
            return f["node_id"]
        node = f.get("attached_node") or f["node_id"]
        if f["resource_type"] in ("model", "snapshot") and not f.get("attached_node"):
            node = f["node_id"]
        if self.is_staging(node):
            srcs = [p for p in self.parents.get(node, []) if p.startswith("source.")]
            if len(srcs) == 1:
                return srcs[0]
        if node and node.startswith("snapshot."):
            srcs = [p for p in self.parents.get(node, []) if p.startswith("source.")]
            if len(srcs) == 1:
                return srcs[0]
        return node


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text or "", re.I)
    return m.group(1) if m else None


def classify(f: dict, lin: Lineage, raw_columns=None, dup_profile=None) -> dict:
    """Return {category, detail, fix_type, extra} for one finding."""
    rt, tn, msg = f["resource_type"], (f.get("test_name") or ""), f.get("message") or ""
    col = (f.get("column") or "").lower()
    extra: dict = {}
    if rt == "metric_guard":
        cat = "metric_shift"
        extra["shifts"] = f.get("metric_shifts", [])
        extra["driver_counts"] = f.get("driver_counts", {})
    elif rt == "source_freshness":
        cat = "stale_source"
        extra["age"] = msg
    elif rt in ("model", "snapshot", "seed") and f["status"] == "error":
        low = msg.lower()
        if "contract" in low:
            cat = "contract_breach"
        elif "binder error" in low and ("not found" in low or "does not have a column" in low):
            cat = "schema_drift"
            missing = _first(r'column "?([A-Za-z0-9_]+)"? not found', msg) or _first(r'does not have a column named "([^"]+)"', msg)
            extra["missing_column"] = missing
            cands = _first(r"Candidate bindings:\s*(.+)", msg)
            pool = list(raw_columns or [])
            if cands and not pool:
                pool = re.findall(r'"([^"]+)"', cands)
            pool = [re.sub(r'^.*\.', '', c) for c in pool]
            if missing:
                best = difflib.get_close_matches(missing, [c for c in pool if c != missing], n=1, cutoff=0.5)
                extra["candidate_column"] = best[0] if best else None
        elif "conversion error" in low or "could not convert" in low:
            cat = "type_drift"
        else:
            cat = "unknown"
    elif rt == "unit_test":
        cat = "logic_regression"
    elif tn == "freshness":
        cat = "stale_source"
    elif tn == "unique" or tn == "dbt_utils_free_unique_combination":
        cat = "duplicate_keys"
        if dup_profile is not None:
            extra["duplicate_profile"] = dup_profile
    elif tn == "not_null":
        if col.endswith("_at") or col.endswith("_date"):
            cat = "timestamp_format_drift" if lin.is_staging(f.get("attached_node")) else "null_values"
        else:
            cat = "null_values"
    elif tn == "mapped_in_seed":
        seed = (f.get("kwargs") or {}).get("seed")
        cat = "unmapped_stage" if seed == "stage_map" else "missing_fx_rate" if seed == "fx_rates" else "unexpected_value"
        extra["unmapped_values"] = sorted({str(r.get("unmapped_value")) for r in f.get("evidence", []) if r.get("unmapped_value") is not None})
        if cat == "unmapped_stage":
            extra["proposed_mappings"] = {v: propose_stage(v) for v in extra["unmapped_values"]}
    elif tn == "relationships":
        cat = "orphan_reference"
    elif tn in ("not_in_future", "singular:assert_stage_entered_after_created"):
        cat = "timezone_or_date_drift"
    elif tn == "singular:assert_closed_won_has_amount_usd":
        curr = {r.get("currency") for r in f.get("evidence", []) if r.get("amount_local") is not None}
        cat = "missing_fx_rate" if curr - {"USD", "GBP", "EUR", None} else "null_values"
    elif tn == "singular:assert_pipeline_reconciles":
        cat = "metric_reconciliation"
    elif tn == "accepted_values":
        cat = "unexpected_value"
    elif tn == "non_negative":
        cat = "invalid_amount"
    elif tn == "singular:assert_open_pipeline_owner_active":
        cat = "null_values"
    else:
        cat = "unknown"
    return {"category": cat, "fix_type": FIX_TYPES[cat], "extra": extra}


def propose_stage(raw_label: str) -> str | None:
    s = raw_label.lower()
    for token, stage in STAGE_RULES:
        if token in s:
            return stage
    return None  # a human chooses


def acknowledged(f: dict, known: list, today: date) -> dict | None:
    for k in known:
        if f["node_id"].startswith(k["node_prefix"]) and f["status"] == "warn":
            exp = date.fromisoformat(k["expires"])
            if today <= exp and (f.get("failures") or 0) <= k.get("max_failures", 0):
                return k
    return None


def build_issues(findings: list, manifest: dict, known: list | None = None, today: date | None = None,
                 raw_columns_fn=None, dup_profile_fn=None) -> dict:
    lin = Lineage(manifest)
    today = today or date(2026, 11, 20)
    acks, rows = [], []
    for f in findings:
        k = acknowledged(f, known or [], today)
        if k:
            acks.append({"node": lin.name(f["node_id"]) or f["node_id"], "failures": f.get("failures"),
                         "reason": k["reason"], "owner": k["owner"], "expires": k["expires"]})
            continue
        root = f.get("root") or lin.root_of(f)
        raw_cols = raw_columns_fn(root) if raw_columns_fn and root else None
        dup = dup_profile_fn(root) if dup_profile_fn and root and f.get("test_name") in ("unique",) else None
        c = classify(f, lin, raw_cols, dup)
        rows.append({**c, "finding": f, "root": root})

    # group by (category, root); error-level first so folding has targets
    issues: dict = {}
    order = sorted(rows, key=lambda r: (r["finding"]["status"] != "error", not lin.is_staging(r["finding"].get("attached_node"))))
    for r in order:
        f, root = r["finding"], r["root"]
        target = None
        # only symptoms on downstream (non-staging) nodes fold; two problems on one staging model stay separate
        if r["category"] in FOLDABLE and not lin.is_staging(f.get("attached_node")) and f["resource_type"] != "source_freshness":
            anc = lin.ancestors(f.get("attached_node") or f["node_id"]) | {f.get("attached_node")}
            for iss in issues.values():
                if iss["status"] == "error" and iss["root"] in anc and iss["category"] != "stale_source" \
                        and (iss["root"] != root or iss["category"] != r["category"]):
                    target = iss
                    break
        key = (r["category"], root)
        if target is None and key in issues:
            target = issues[key]
            target["symptoms"].append(_symptom(f, lin))
            target["extra"] = _merge(target["extra"], r["extra"])
            if f["status"] == "error":
                target["status"] = "error"
            continue
        if target is not None:
            target["folded"].append({**_symptom(f, lin), "category": r["category"]})
            continue
        issues[key] = {"category": r["category"], "root": root, "root_name": lin.name(root), "status": f["status"],
                       "fix_type": r["fix_type"], "extra": r["extra"], "symptoms": [_symptom(f, lin)], "folded": []}

    out = []
    for i, iss in enumerate(sorted(issues.values(), key=lambda x: (x["status"] != "error", x["category"], x["root_name"])), 1):
        desc = lin.descendants(iss["root"]) if iss["root"] else set()
        exposures = sorted(lin.name(d) for d in desc if d.startswith("exposure."))
        models = sorted(lin.name(d) for d in desc if d.startswith("model."))
        sev = "high" if iss["status"] == "error" and exposures else "medium" if iss["status"] == "error" else "low"
        if iss["category"] in ("stale_source", "metric_shift") and iss["status"] == "error":
            sev = "high" if exposures else "medium"
        out.append({"issue_id": f"ISS-{i:02d}", **iss, "severity": sev,
                    "blast_radius": {"models": models, "exposures": exposures}})
    return {"issues": out, "acknowledged": acks}


def _symptom(f: dict, lin: Lineage) -> dict:
    return {"node": lin.name(f["node_id"]) or f["node_id"], "node_id": f["node_id"], "status": f["status"],
            "model": lin.name(f.get("attached_node")),
            "failures": f.get("failures"), "test": f.get("test_name"), "column": f.get("column"),
            "evidence": f.get("evidence", [])[:3]}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = sorted(set(out[k]) | set(v))
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        elif k not in out or out[k] is None:
            out[k] = v
    return out


def publication_gate(issues: list) -> dict:
    blocking = [i for i in issues if i["severity"] == "high" or (i["status"] == "error" and i["blast_radius"]["exposures"])]
    exps = sorted({e for i in blocking for e in i["blast_radius"]["exposures"]})
    return {"hold": bool(blocking), "exposures": exps, "because": [i["issue_id"] for i in blocking]}
