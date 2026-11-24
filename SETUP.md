# Setup

Tested on Python 3.13 in a fresh venv with the pins in `requirements.txt` (dbt-core 1.12.7, dbt-duckdb 1.11.1,
duckdb 2.0.1). No warehouse, no credentials, no API key.

## 1. Install and run the sample

```bash
git clone https://github.com/rubianaseem/gtm-dbt-revenue-models.git
cd gtm-dbt-revenue-models
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_demo.py                          # clean run + synthetic incident, about 30 seconds
python run_evals.py                         # 25 scenarios, about 5 minutes
python -m evals.failure_suite               # 24 scenarios, about 40 seconds
python -m unittest discover -s tests -t .
```

dbt v2 is now the default for new dbt installs. This repo pins the v1 line (dbt-core 1.12) because that is what
dbt-duckdb supports today and what I tested. If you move to v2, follow the dbt upgrade guide and re-run all four
commands.

## 2. Use dbt directly

```bash
python -c "from gtm_dbt.loader import load_raw; print(load_raw('data/raw', 'warehouse/gtm.duckdb'))"
cd dbt
dbt source freshness --profiles-dir .       # dbt build does not run freshness
dbt build --profiles-dir .                  # seeds, snapshot, 18 models, data tests, 1 unit test
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .
```

## 3. The agent step by step

```bash
python agent.py run                                   # writes outputs/run/latest/
python agent.py run --scenario evals/scenarios_v1/dev.json#D05
python agent.py show                                  # report + plan SHA-256
python agent.py approve --approver rubia --sha256 <64-hex> --held CHG-01 --value "CHG-01.rate_to_usd:AUD=0.66"
python agent.py release --verify-sandbox              # files only, then a sandbox rebuild
python agent.py verify                                # audit and approvals hash chains
python agent.py accept-baseline --approver rubia      # after a clean run you trust
```

Approvers live in `config/approvers.json`. Accepted known warnings (with owner and expiry) live in
`config/known_issues.json`.

## 4. Optional Claude summaries

```bash
pip install -r requirements-optional.txt
cp .env.example .env    # add ANTHROPIC_API_KEY, then: set -a; source .env; set +a
python agent.py run
```

Claude only re-words issue summaries. Output that fails validation is replaced by the template and logged.

## 5. Real data

1. Land HubSpot and Salesforce in your warehouse with a managed connector (Fivetran or Airbyte), or with
   your own load job. Note each table's sync timestamp column (`_fivetran_synced` for
   Fivetran, `_airbyte_extracted_at` for Airbyte).
2. Point the sources at your schemas in `dbt/models/staging/*/_*__sources.yml` (`schema:`, `loaded_at_field:`),
   and adjust column names in the staging models. Typed columns from a connector simplify `parse_ts()`.
3. Add a profile. Snowflake:
   ```yaml
   gtm_revenue:
     target: prod
     outputs:
       prod:
         type: snowflake
         account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
         user: "{{ env_var('SNOWFLAKE_USER') }}"
         authenticator: externalbrowser
         role: TRANSFORMER
         warehouse: TRANSFORMING
         database: ANALYTICS
         schema: dbt_gtm
         threads: 8
   ```
   BigQuery: `type: bigquery`, `method: oauth`, `project:`, `dataset:`. Install `dbt-snowflake` or `dbt-bigquery`.
   The SQL uses DuckDB functions (`regexp_matches`, `try_cast`, `date_diff`, `quantile_cont`); swap them for
   your warehouse's equivalents, or use `dbt.dateadd`-style cross-database macros.
4. Replace the seeds with your stage map, your finance team's rate table and your quotas.
5. Run the agent against the artifacts of your scheduled job. `gtm_dbt/dbt_runner.py` shells out to `dbt`; point it
   at your project or feed `artifacts.parse()` the `target/` folder your orchestrator produces.

## 6. Extending with Cursor, Claude Code, Codex CLI or Grok

Open the repo and ask the agent to read `CLAUDE.md` and `AGENTS.md` first. Good first tasks: a mart for pipeline
created by source, a triage rule for `accepted_values` on lifecycle stage, a Slack message from `report.md`
behind the same approval. Ask it to add a scenario to a new `scenarios_v2` set for every new rule.

## Troubleshooting

- `dbt executable not found`: activate the venv; the runner looks next to the Python it runs under, then on PATH.
- Everything stale in freshness: `_fivetran_synced` is set by the loader to the real clock; if you load raw data and
  wait 12 hours, freshness warns. That is correct behaviour. Re-run the loader.
- `Binder Error` in a staging model: the raw export changed shape; run `python agent.py run` and read the plan.
- `IO Error: Could not set lock on file`: another process has the DuckDB file open (for example a notebook).
- Contract errors after editing a mart: update the column list and `data_type` in `models/marts/_marts.yml`, or
  version the model.
