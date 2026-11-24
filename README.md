# GTM dbt Revenue Models

**A tested dbt project over messy HubSpot and Salesforce data, plus an agent that reads dbt's own artifacts when something breaks. It finds the root cause, proposes the fix as a reviewable change plan, and releases nothing until a named person approves the plan's SHA-256.**

Built by Rubia Naseem, GTM Engineer (12+ yrs CRM/RevOps, HubSpot & Salesforce).

Status: implemented and tested locally on synthetic data (roadmap item 14, dbt on GTM data). Runs on dbt-core 1.12 with DuckDB, no warehouse or credentials.

## The problem

My [SQL repo](https://github.com/rubianaseem/gtm-sql-revops-queries) answered the weekly RevOps questions in plain SQL. Here they become a layered dbt project with tests and contracts. Then comes the part that eats a Monday morning: working out why the build went red, or why it stayed green while the numbers were wrong.

The dbt docs explain why "the build passed" is not enough:

- "`dbt build` does *not* include source freshness checks when building and testing resources in your DAG." ([dbt docs: source freshness](https://docs.getdbt.com/docs/deploy/source-freshness))
- "Data tests return a set of failing records." ([dbt docs: data tests](https://docs.getdbt.com/docs/build/data-tests)) Someone still has to trace them upstream and decide what to change.

Silent failures are the other half: "Row-count checks and basic referential integrity would miss it completely." ([@TechSoulGeeta on X](https://x.com/TechSoulGeeta/status/2124117125891821947))

## What it does

- **Models GTM data in dbt.** Eight staging models, five intermediate and five contracted marts: pipeline snapshot, funnel conversion, stage velocity, lead-to-opportunity attribution and owner coverage. Plus seeds, source freshness, a snapshot, 58 data tests (custom generic and singular ones included) and a unit test.
- **Ships realistic mess.** Duplicate contacts, stage label variants, `' gbp '` currencies, three timestamp formats, soft deletes, an inactive owner and prompt injection in deal notes, all synthetic.
- **Triages from artifacts.** The agent reads `run_results.json`, `manifest.json` and `sources.json`. It maps each failure to a root source, folds downstream symptoms into one issue and sets severity from lineage to exposures. Accepted known warnings stay quiet until they grow or expire.
- **Catches silent changes.** A metric guard compares pipeline, bookings and attribution with a baseline a person accepted, and names the deals behind any jump (for example, amounts entered in cents).
- **Proposes fixes it can prove.** It writes seed rows, a staging diff for a renamed field and CRM-admin tasks. Values only a person knows, like an FX rate, are left blank. Approved patches are rebuilt in a sandbox to show they work.

## Where each step runs

1. **GitHub** stores the dbt project, the agent, the synthetic data and the scenario sets.
2. **Your terminal** (Mac Terminal or the Cursor terminal) runs `dbt build` and `python agent.py run`. No API key needed.
3. **Optional Claude** re-words issue summaries only. Output that names an unknown model or number is replaced by the template.
4. **You review** `report.md` and `change_plan.json`, approve the hash, and take the released files to a pull request, your ticket queue or the CRM admin.
5. **The agent writes nothing to real tools.** Release writes files under the run folder. No CRM, warehouse or repo writes, and no Clay.

## Guardrails and human in the loop

- Only a named human in `config/approvers.json` can approve, using the full SHA-256 of the plan. Agent, model and CI identities are refused. Approvals expire after 24 hours and editing the plan or project voids them. There is no auto-approve flag.
- Changes that alter numbers or code (seed mappings, diffs, dedupe decisions) are held until listed by name. Human values are validated and logged in a hash-chained file.
- CRM free text never reaches a report, plan or prompt. Broken dbt runs fail closed and publication is held.

## Quick start

```bash
git clone https://github.com/rubianaseem/gtm-dbt-revenue-models.git
cd gtm-dbt-revenue-models
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_demo.py
python run_evals.py
python -m evals.failure_suite
python -m unittest discover -s tests -t .
```

## Example output (from outputs/demo_transcript.txt)

```text
dbt build: {'success': 14, 'pass': 40, 'fail': 4, 'skipped': 24, 'warn': 1}   (exit 1; source freshness exit 1)
  ISS-02 high   missing_fx_rate        salesforce.opportunities         symptoms 1
  ISS-04 high   stale_source           hubspot.contacts                 symptoms 1
  ISS-05 high   unmapped_stage         salesforce.opportunity_history   symptoms 1
  publication gate: HOLD campaign_attribution_report, weekly_pipeline_review
  approve as claude-agent: REFUSED ('claude-agent' is an agent, model or service identity and can never approve)
  sandbox applied ['seed:fx_rates', 'seed:stage_map']
  release again: wrote 0 (already released 5)
```

## Results (`python run_evals.py`)

25 failure-injection scenarios against a "read the red tests" baseline. Held-out (10, hashed before tuning): issues found 9/11 vs 1/11, raised issues correct 9/10 vs 1/24, hold decision 10/10 vs 9/10, silent issues 3/3 vs 0/3. Dev: 15/15 vs 5/15. The held-out misses were a DuckDB error wording the schema-drift rule did not know, and a missing `not_null` test in the project. Failure suite 24/24; 24 unit tests. I wrote the data, scenarios and rules, so treat these as regression checks. Details: [docs/EVALUATION.md](docs/EVALUATION.md).

## Walk through it line by line

[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) teaches the key code, from sources and contracts to the approvable plan.

## More

[SETUP.md](SETUP.md) | [Architecture](docs/ARCHITECTURE.md) | [Evaluation](docs/EVALUATION.md) | [Details, costs, stack swaps](docs/DETAILS.md) | [Sources](docs/SOURCES.md)

Builds on my repos: [gtm-sql-revops-queries](https://github.com/rubianaseem/gtm-sql-revops-queries) (the same questions in plain SQL), [gtm-agent-eval-harness](https://github.com/rubianaseem/gtm-agent-eval-harness), [agent-decision-log](https://github.com/rubianaseem/agent-decision-log), [crm-change-control-plane](https://github.com/rubianaseem/crm-change-control-plane), [revenue-signal-router](https://github.com/rubianaseem/revenue-signal-router) (approval, audit and screen adapted)
