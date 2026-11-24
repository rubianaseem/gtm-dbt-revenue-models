# Details

## API cost assumptions (optional Claude path only)

One call per agent run, only when there are issues. Input is the structured issue list (about 300 to 600 tokens per
issue, no rows of CRM data); output is one or two sentences per issue. A five-issue incident is roughly 3,000 input
and 400 output tokens. At $3 per million input tokens and $15 per million output tokens that is about 1.5 US cents
per run; check current Anthropic pricing for the model you set in `ANTHROPIC_MODEL`. The deterministic path (no key) costs nothing beyond your warehouse compute. Warehouse cost is
dominated by `dbt build`; the agent adds one `dbt source freshness` and reads at most five failing rows per test.

## Stack swap table

| Here | Production equivalent |
|---|---|
| CSV + `gtm_dbt/loader.py` | Fivetran or Airbyte HubSpot and Salesforce connectors |
| DuckDB file | Snowflake, BigQuery, Databricks, Redshift (dbt adapter) |
| dbt-core CLI via subprocess | dbt Cloud job artifacts API, or an Airflow/Dagster/Prefect task that hands over `target/` |
| `config/approvers.json` | Your identity provider groups; approval in a pull request review or a Slack approval step |
| `released/` files | A pull request (seed rows, staging diff), Jira or Linear tickets (CRM tasks), a BI tool annotation (hold) |
| Hash-chained JSONL audit | Append-only table in the warehouse (see my agent-decision-log repo) |
| Template or Claude summaries | Any model behind the same validator |

## Customise for your stack

- Stage names: edit `dbt/seeds/stage_map.csv`. Add a row per raw label; the triage proposes a canonical stage only
  when a keyword rule in `triage.STAGE_RULES` matches.
- FX: replace `fx_rates.csv` with your finance table; if rates are dated, join on month in `int_opportunities__enriched`.
- Freshness SLAs: `warn_after` and `error_after` per source table in the sources files.
- Metric guard: thresholds in `config/metric_guard.json`; accept a new baseline only from a clean run with
  `python agent.py accept-baseline --approver <name>`.
- Known warnings: `config/known_issues.json` with owner, maximum rows and expiry. Growth past the maximum or expiry
  raises the issue again.

## How this runs today (and what production would add)

Today:
- Local DuckDB, synthetic data, one fixed as-of date. Every agent run rebuilds a fresh warehouse in its run folder,
  so the snapshot holds a single version per run (idempotency and change capture are tested separately in F21).
- Freshness uses the real clock because dbt does; the loader stamps `_fivetran_synced` with the current time.
- Triage rules and scenarios were written by me, on data I generated. The results are regression checks, not
  field accuracy.
- The optional Claude path is tested with a scripted model only; I have not measured real model summaries.
- Approval is a CLI command with an approvers file, not an identity provider.

Production would add:
- Running against the artifacts of the scheduled dbt job instead of local builds, and storing triage history so
  repeated issues are linked across runs.
- Releasing as a pull request and tickets through their own approval flows, with the plan hash in the PR body.
- dbt unit tests for every intermediate model and `store_failures` retention rules.
- A real metric baseline per week and per segment, with seasonality, instead of one accepted snapshot.
- Alerting (Slack) gated by the same severity and publication rules.
