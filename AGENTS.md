# AGENTS.md

Instructions for coding agents (Cursor, Claude Code, Codex CLI, Grok and others).

- Read CLAUDE.md first; the same rules apply to every agent.
- Layout: `dbt/` (dbt project: sources, staging, intermediate, marts, seeds, snapshots, tests, macros),
  `gtm_dbt/` (loader, dbt runner, artifact parser, triage, metric guard, plan, approval, release, narrate),
  `config/` (approvers, known issues, metric baseline and thresholds, demo incident), `evals/` (scenarios, baseline,
  failure suite), `tests/` (unittest), `data/` (generator and raw synthetic export), `docs/`, `outputs/demo/` (committed demo run).
- Definition of done: the commands in CLAUDE.md pass; `outputs/eval_report.md` and `outputs/demo_transcript.txt`
  regenerated; README under 900 words; numbers in docs match the latest run.
- Safe extension points: a new mart (add a contract and tests), a new triage rule (add a unit test and a new scenario
  set), a new source (sources.yml with freshness, a staging model, tests), a real warehouse profile (SETUP.md).
- Not allowed without the repo owner's explicit approval: real CRM or warehouse writes, Clay usage, weakening approval
  checks, editing scenarios_v1, committing secrets or `.env`.
