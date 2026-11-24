# Walk through it line by line

The order I would read this repo in if I were learning dbt on GTM data. If you have read my
[gtm-sql-revops-queries](https://github.com/rubianaseem/gtm-sql-revops-queries), the SQL will look familiar: the
same questions (funnel, velocity, coverage, attribution), now as a tested, layered dbt project.

## 1. Sources: where raw data lands, and how fresh it must be

```yaml
sources:
  - name: salesforce
    schema: raw_salesforce
    loaded_at_field: _fivetran_synced
    freshness:
      warn_after: {count: 12, period: hour}
      error_after: {count: 36, period: hour}
```
`source('salesforce', 'opportunities')` now means "the raw table the connector writes". `loaded_at_field` is the
column dbt reads to decide freshness. The catch from the dbt docs: `dbt build` does not run freshness, so a
pipeline can be green while yesterday's data sits in every dashboard. The agent runs `dbt source freshness` first.

## 2. A macro for the timestamp mess

```sql
{% macro parse_ts(col) -%}
    case
        when regexp_matches(trim({{ col }}), '(Z|[+-][0-9]{2}:?[0-9]{2})$')
            then (try_cast(trim({{ col }}) as timestamptz) at time zone 'UTC')
        else try_cast(trim({{ col }}) as timestamp)
    end
{%- endmacro %}
```
CRM exports mix `...Z`, `...+01:00` and naive `2026-10-05 11:00:00`. Offset-aware strings are converted to UTC;
naive ones are treated as UTC. `try_cast` returns NULL instead of crashing, and a `not_null` test on the column
turns that NULL into a loud failure. The profile also sets the session `TimeZone: UTC`, so the result does not
depend on the laptop it runs on.

## 3. Staging: type and clean, never decide

```sql
-- No dedupe here on purpose: a duplicate id from the connector must fail the
-- unique test so a person decides what happened, rather than staging silently picking a row.
select
    cast(id as varchar)                              as opportunity_id,
    try_cast(nullif(trim(amount), '') as double)     as amount_local,
    upper(trim(currency_iso_code))                   as currency,
```
One staging model per source table. It renames, casts and trims (`' gbp '` becomes `GBP`). It does not pick
between duplicate rows: that would change pipeline numbers with nobody noticing.

## 4. Intermediate: dedupe people, collapse stage history

```sql
row_number() over (partition by coalesce(email, 'id:' || contact_id)
                   order by created_at desc, contact_id desc) as rn
```
Contacts that differ only by case or whitespace in the email become one person; the latest record wins. Contacts
with no email keep their own key, so they are not merged with each other.

```sql
marked as (
    select *, lag(stage) over (partition by opportunity_id order by stage_entered_at) as prev_stage
    from hist
),
spells as (select ... from marked where prev_stage is null or prev_stage <> stage)
```
`lag()` looks at the previous history row. "Discovery" followed by "discovery " is one stage, so only changes
start a new spell. `lead()` then finds when the spell ended and `days_in_stage` is the gap. A dbt unit test
(`_intermediate.yml`) feeds three fake rows and checks exactly that.

## 5. Marts with contracts

```yaml
- name: fct_pipeline_snapshot
  config: {contract: {enforced: true}}
  columns:
    - {name: open_opportunities, data_type: integer}
```
A contract is a promise about column names and types. If a pull request changes `cast(count(*) as integer)` to
`count(*)` (a BIGINT in DuckDB), the model does not build. Scenario D11 in the evals does exactly this.

## 6. Tests you write yourself

```sql
{% test mapped_in_seed(model, column_name, seed, seed_column, normalise=true) %}
select value as unmapped_value, count(*) as row_count
from vals
where value not in (select {{ seed_column }} from {{ ref(seed) }})
group by 1
{% endtest %}
```
A generic test is a SELECT that returns failing rows. This one returns each unmapped stage label or currency with
a count, which is exactly the evidence the agent needs to propose a seed row. Singular tests in `dbt/tests/`
check business rules: pipeline in the mart equals the open opportunities it came from; a stage cannot start before
its opportunity was created.

## 7. Snapshot for stage history

```yaml
snapshots:
  - name: snap_salesforce__opportunities
    relation: source('salesforce', 'opportunities')
    config: {unique_key: id, strategy: check, check_cols: [stage_name, amount, close_date, owner_id, currency_iso_code]}
```
Each run compares the current row with the last stored version and adds a new version only when a checked column
changed. Failure scenario F21 proves a re-run adds zero rows and one stage change adds exactly one.

## 8. The agent: read artifacts, not logs

```python
fr = _run([exe, "source", "freshness", ..., "--target-path", str(fr_dir)], ...)
bd = _run([exe, "build", ..., "--target-path", str(bd_dir)], ...)
```
Two invocations with separate target folders, because both write artifacts. `run_results.json` says which node
passed, failed, warned, errored or was skipped. `manifest.json` gives the lineage (`parent_map`, `child_map`).

```python
if k.endswith("_untrusted") or k in ("notes", "description"):
    ...  # screened for the audit log, then dropped
    continue  # free text never leaves this function
```
Failing rows come from the `store_failures` tables. Deal descriptions and contact notes are dropped here, before
any report, plan or prompt sees them.

## 9. Root cause, not one ticket per red test

```python
if self.is_staging(node):
    srcs = [p for p in self.parents.get(node, []) if p.startswith("source.")]
    if len(srcs) == 1:
        return srcs[0]
```
A test on a staging model is really about its source table. Then folding: when a new stage label fails the
mapping test in staging, the `not_null` test on `stage` in the intermediate model fails too. Both share an
upstream root, so the second becomes a folded symptom of the first instead of a separate ticket.

## 10. A plan a person can approve

```python
return {**base, "requires_human_input": [f"rate_to_usd:{c}" for c in curr],
        "patch": {"kind": "seed_rows", "seed": "fx_rates",
                  "rows": [{"currency": c, "rate_to_usd": None, ...}]}}
```
The agent proposes the seed row and leaves the rate empty: finance owns that number. Approval validates the value
the human types (`0 < rate < 1000`), records it in a hash-chained log, and binds it to the SHA-256 of the plan.

```python
key = f"{m['plan_sha256'][:16]}:{c['change_id']}"
if key in done:
    skipped.append(c["change_id"])
    continue
```
Release writes one file per change and records it in a ledger straight after, so a crash and a re-run never write
anything twice. `verify_in_sandbox()` then copies the project and warehouse, applies the patches and rebuilds, so
you see whether the fix works before you open the pull request.
