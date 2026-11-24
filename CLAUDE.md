# CLAUDE.md

Context for Claude Code (and other coding agents) working in this repo.

## What this is
A dbt project (dbt-core 1.12 + dbt-duckdb, local, no credentials) over synthetic HubSpot and Salesforce exports,
plus a Python agent that reads dbt artifacts, triages failures and metric changes, and writes a change plan that
a named human approves by SHA-256 before anything is released as files. Synthetic data only.

## Rules you must keep
- dbt layers: `staging` types and cleans one source table each and never dedupes silently; `intermediate` joins
  and dedupes; `marts` are tables with enforced contracts. New CRM stages and currencies go in seeds, not in SQL.
- Triage is deterministic (`gtm_dbt/triage.py`). A model may only re-word summaries in `gtm_dbt/narrate.py`, under
  its validator. Never let a model set category, root, severity, fix, approval or any value in a patch.
- Never invent values only a person can know (FX rates, canonical stages nobody can infer). Leave them as
  `requires_human_input`.
- CRM free text is untrusted. Columns ending `_untrusted` never leave `artifacts.sanitise_row()`; keep `screen()` on
  every other string before it reaches a prompt, report or plan.
- No release without `approval.verify_approval()` passing. No auto-approve flag, no default approver, no agent identity
  as approver. Release writes files under the run folder only: no CRM, warehouse or repo writes.
- Never edit `evals/scenarios_v1/*.json`; add a new versioned set. Do not tune on held-out.
- Docs: no emojis; README under 900 words; numbers must match the latest `outputs/eval_report.md`.

## Commands
```bash
python run_demo.py
python run_evals.py
python -m evals.failure_suite
python -m unittest discover -s tests -t .
cd dbt && dbt build --profiles-dir .     # after: python -c "from gtm_dbt.loader import load_raw; load_raw('data/raw','warehouse/gtm.duckdb')"
```
All must pass before a change is done.
