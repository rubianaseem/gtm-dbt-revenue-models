# Architecture

```
 data/raw/*.csv (synthetic HubSpot + Salesforce export)       config/demo_incident.json, evals/scenarios_v1
          |                                                              | (mutations applied to a COPY)
          v                                                              v
 gtm_dbt/loader.py  -> DuckDB raw_hubspot.*, raw_salesforce.*  (+ _fivetran_synced)
          |
          v
 dbt source freshness  -> sources.json        (dbt build does not run freshness)
 dbt build             -> run_results.json, manifest.json, store_failures tables
   seeds:        stage_map, fx_rates, quotas
   staging (8):  type + clean one source each; no silent dedupe
   intermediate: int_contacts__deduped, int_contact_id_map, int_opportunities__enriched,
                 int_opportunity__stage_spells (unit-tested), int_touches__attributed
   marts (contracted tables): fct_pipeline_snapshot, fct_funnel_conversion, fct_stage_velocity,
                 fct_lead_to_opportunity_attribution, rpt_owner_coverage
   snapshot:     snap_salesforce__opportunities (check strategy)
   exposures:    weekly_pipeline_review, campaign_attribution_report
          |
          v
 gtm_dbt/artifacts.py   findings; failing rows read from store_failures, free text dropped or screened
 gtm_dbt/metric_guard.py key metrics vs accepted baseline; drivers per opportunity
 gtm_dbt/triage.py      category -> root (staging test -> its source) -> fold downstream symptoms ->
                        known-issue register -> severity from lineage to exposures -> publication gate
 gtm_dbt/narrate.py     template summaries; optional Claude re-wording under a validator
 gtm_dbt/plan.py        change_plan.json (deterministic bytes, SHA-256)
          |
          v
 human: agent.py approve --approver <named human> --sha256 <hash> [--held ...] [--value ...]
          |
          v
 gtm_dbt/release.py     files under <run>/released/ (+ ledger)  ->  optional sandbox rebuild proof
```

## Data contracts

| Artifact | Fields |
|---|---|
| Finding | node_id, resource_type (test, model, snapshot, seed, unit_test, source_freshness, metric_guard), status (error or warn), raw_status, failures, message, test_name, column, kwargs, attached_node, evidence (max 5 sanitised rows) |
| Issue | issue_id, category, root (source or model unique_id), root_name, status, severity (high, medium, low), fix_type, extra (unmapped values, missing and candidate column, duplicate profile, metric shifts), symptoms, folded, blast_radius {models, exposures} |
| Change | change_id, issue_id, type, target, held, requires_human_input (e.g. `rate_to_usd:AUD`, `stage:legal review`), patch (seed_rows or code with per-file edits and a unified diff), action, record_ids |
| Plan | plan_version, inputs {raw_sha256, project_sha256, as_of_date, sync_lag_hours, metric_baseline_run}, publication_gate, issues, changes. No timestamps, so identical inputs give an identical hash |
| Approval | approver, approver_name, plan_sha256, held_changes_approved, human_values, expires_at, seq, prev_hash, hash |
| Release ledger | key (plan hash prefix + change_id), change_id |
| Trace | one JSON line per step: span, ms, status, step attributes (rows loaded, dbt exit codes, issue count, summary mode) |

## Triage categories

stale_source, schema_drift, type_drift, contract_breach, duplicate_keys, null_values, timestamp_format_drift,
unmapped_stage, missing_fx_rate, orphan_reference, timezone_or_date_drift, metric_reconciliation, metric_shift,
unexpected_value, invalid_amount, logic_regression, dbt_invocation_failed, unknown.

Folding: a finding on a non-staging node whose category can be a downstream symptom is attached to an existing
error-level issue whose root is one of its ancestors. Two problems on one staging model stay separate.

## Hard controls (in code, each tested)

- No release without a named human approving the full plan hash; agent, model, CI and service identities refused;
  24-hour expiry; plan or project edits void approval.
- Held changes are released only when listed; required human values are validated (rate in (0, 1000), canonical stage).
- Release writes files only; sandbox verification copies the project and the warehouse first.
- Free text columns never leave the sanitiser; other strings are screened.
- dbt failures, missing binaries and unreadable artifacts fail closed with publication held.
