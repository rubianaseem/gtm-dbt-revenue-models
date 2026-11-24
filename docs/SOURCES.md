# Sources

Primary documentation read on 2026-11-24:

- dbt, Model contracts: https://docs.getdbt.com/docs/mesh/govern/model-contracts
- dbt, Source freshness: https://docs.getdbt.com/docs/deploy/source-freshness
- dbt, Data tests: https://docs.getdbt.com/docs/build/data-tests
- dbt, Snapshots: https://docs.getdbt.com/docs/build/snapshots
- dbt, Run results artifact: https://docs.getdbt.com/reference/artifacts/run-results-json

Inspiration (patterns only, no code or text reused):

- fivetran/dbt_hubspot and fivetran/dbt_salesforce (Apache-2.0): https://github.com/fivetran/dbt_hubspot,
  https://github.com/fivetran/dbt_salesforce. Pattern: source/staging/model layering for CRM connector schemas.
- Towards Data Science on X, 10 Nov 2026: https://x.com/TDataScience/status/2120294435770577320. Pattern: AI in a
  data pipeline guarded by Python checks and dbt tests.
- @TechSoulGeeta on X, 21 Nov 2026: https://x.com/TechSoulGeeta/status/2124117125891821947. Pattern: silent failures
  that row counts and referential checks miss; compare distributions after each run.

Builds on my repos: gtm-sql-revops-queries (the same RevOps questions in plain SQL), gtm-agent-eval-harness,
agent-decision-log, crm-change-control-plane, revenue-signal-router.
