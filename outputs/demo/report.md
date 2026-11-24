# dbt triage report (run-f8bfab7480d4)

dbt build: {'success': 14, 'pass': 40, 'fail': 4, 'skipped': 24, 'warn': 1}
Publication gate: HOLD campaign_attribution_report, weekly_pipeline_review
Metric guard: unavailable
Summaries: template

## Issues

- **ISS-01 duplicate_keys** at `salesforce.opportunities` (high): Duplicate keys at salesforce.opportunities (error, severity high). Seen in: unique_stg_salesforce__opportunities_opportunity_id. 3 duplicate ids (2 identical, 1 conflicting). Blocks: campaign_attribution_report, weekly_pipeline_review.
- **ISS-02 missing_fx_rate** at `salesforce.opportunities` (high): Missing fx rate at salesforce.opportunities (error, severity high). Seen in: mapped_in_seed_stg_salesforce__opportunities_currency__False__fx_rates__currency. Unmapped values: AUD. Blocks: campaign_attribution_report, weekly_pipeline_review.
- **ISS-03 null_values** at `salesforce.opportunities` (high): Null values at salesforce.opportunities (error, severity high). Seen in: not_null_stg_salesforce__opportunities_owner_id. Blocks: campaign_attribution_report, weekly_pipeline_review.
- **ISS-04 stale_source** at `hubspot.contacts` (high): Stale source at hubspot.contacts (error, severity high). Seen in: hubspot.contacts. Blocks: campaign_attribution_report.
- **ISS-05 unmapped_stage** at `salesforce.opportunity_history` (high): Unmapped stage at salesforce.opportunity_history (error, severity high). Seen in: mapped_in_seed_stg_salesforce__opportunity_history_stage_raw__stage_map__raw_stage. Unmapped values: legal review. Blocks: weekly_pipeline_review.

## Accepted known issues (not raised)

- relationships_stg_salesforce__opportunity_history_opportunity_id__opportunity_id__ref_stg_salesforce__opportunities_: 1 row(s). Stage history rows for soft-deleted opportunity 006O0077 (synthetic). Accepted until the history sync filters deleted parents. Owner revops, expires 2027-01-31.

## Proposed changes (nothing happens until a named person approves the plan hash)

- CHG-01 [duplicate_investigation, HELD] 3 duplicate id(s) in salesforce.opportunities (conflicting rows share an id. Investigate in the CRM before any dedupe rule is written; picking a row silently would change pipeline.)
- CHG-02 [seed_row_add, HELD] Currency AUD has no plan rate, so those deals drop out of USD pipeline. Finance supplies the rate; the agent never guesses one. Needs human input: rate_to_usd:AUD.
- CHG-03 [crm_fix_task] CRM admin task: fix null values on salesforce.opportunities for the listed records, then re-run dbt.
- CHG-04 [connector_check] Check the connector sync for hubspot.contacts (max loaded 40.0h ago). Do not publish downstream exposures until a fresh load lands, then re-run dbt.
- CHG-05 [seed_row_add, HELD] New CRM stage label(s) are not mapped. Confirm the proposed canonical stage (or choose one) so funnel and velocity stay comparable. Needs human input: stage:legal review.
- CHG-06 [publication_hold] Hold campaign_attribution_report, weekly_pipeline_review until ISS-01, ISS-02, ISS-03, ISS-04, ISS-05 are resolved.

4 free-text value(s) quarantined (record ids and pattern ids only are in audit.jsonl).

Plan SHA-256: `aea49680d870700ead95dc703d510702d981b7c16717de9efe3c26a8ddc12fdc`
