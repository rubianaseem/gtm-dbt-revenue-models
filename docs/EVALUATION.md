# Evaluation

Everything here is reproducible with:

```bash
python run_evals.py                  # writes evals/results.json and outputs/eval_report.md (about 5 minutes)
python -m evals.failure_suite        # writes outputs/failure_suite.txt
python -m unittest discover -s tests -t .
```

Numbers below are from a fresh venv on the box on 2026-11-24 (Python 3.13.5, dbt-core 1.12.7, dbt-duckdb 1.11.1,
duckdb 2.0.1, no API key).

## Scenario sets (`evals/scenarios_v1/`, SHA-256 in `evals/scenarios_v1.sha256`)

Each scenario applies mutations to a copy of the synthetic raw export (or, for pull-request scenarios, to a copy of
the dbt project), runs `dbt source freshness` and `dbt build`, then runs the agent and the baseline on the same
artifacts. Expected issues are (category, root) pairs I wrote before running the agent on them.

- dev, 15 scenarios: used while building the rules.
- held-out, 10 scenarios: written and hashed before any tuning; not used to change rules. The runner warns if a file
  no longer matches its hash.

Failure types covered: stale source (3 tables), schema drift (column renames), duplicate ids (identical and
conflicting), new stage labels, new or mistyped currencies, null owners, date format drift, future-dated and
back-dated timestamps, orphan references, contract breaks from code changes, negative amounts, amounts in cents
(no test fails), prompt injection in deal descriptions, and combinations.

## Baseline: "read the red tests"

What a person does with `dbt build` output alone: one ticket per non-passing node, categorised by the generic test
name, staging nodes mapped to their source (the same root normalisation as the agent), no freshness, no metric
comparison, no known-issue register, no folding. Publication held when `dbt build` exits non-zero.

## Results

| metric | dev agent | dev baseline | held-out agent | held-out baseline |
|---|---|---|---|---|
| expected issues found | 15/15 | 5/15 | 9/11 | 1/11 |
| raised issues that were correct | 15/15 | 5/34 | 9/10 | 1/24 |
| publication hold decision correct | 15/15 | 13/15 | 10/10 | 9/10 |
| fix detail correct (candidate column, required human input, duplicate profile) | 5/5 | 0/5 | 3/4 | 0/4 |
| silent issues found (stale source, metric shift) | 3/3 | 0/3 | 3/3 | 0/3 |
| sandbox rebuild proves the approved fix | 3/3 | - | 1/2 | - |
| injected free text in report, plan, audit or prompt | 0 | - | 0 | - |
| scripted bad model output rejected, template used | 14/14 runs with issues | - | 9/9 | - |

The baseline's low precision is mostly noise it cannot avoid: it raises the two accepted known warnings on every
run and one ticket per symptom.

## Held-out misses (reported, not fixed in v1)

- H02 (HubSpot `email` renamed to `email_address`): DuckDB raised a different binder message ("referenced that
  exists in the SELECT clause - but this column cannot be referenced before it is defined") because the staging
  model also aliases a column called `email`. The rule only knew the "not found" wording, so the issue was raised as
  `unknown` with root `hubspot.contacts` and no patch. Publication was still held. This also caused the fix-detail
  and sandbox misses.
- H08 (blank contact ids on touches): the CSV loader reads blanks as NULL and the project has no `not_null` test on
  `stg_hubspot__touches.contact_id`; `relationships` ignores NULLs. No test failed and the metric guard did not
  move past its thresholds, so neither the agent nor the baseline saw it. This is a test-coverage gap in the dbt
  project, not a triage miss.

Next version (scenarios_v2): add the second binder wording and a `not_null` test on touch contact ids, then
measure on a new held-out set.

## Failure suite (24/24)

Approval bypasses (agent identities, unknown approver, wrong hash, edited plan, expiry, held changes not listed,
missing or invalid human values, approver without held permission, stray values, no approval at all), idempotency
(double release, crash mid-release and resume, identical plan hash on re-run, snapshot re-run), tampering (audit and
approvals hash chains), fail-closed runs (missing dbt binary, corrupted artifacts), safety (injection never reaches
outputs or prompts, sandbox leaves repo and warehouse untouched), and model behaviour (invented nodes or numbers
rejected, rate limits and timeouts fall back). Full output: `outputs/failure_suite.txt`.

## Caveats

I generated the data, wrote the scenarios and wrote the rules, so treat these numbers as regression checks, not
field accuracy. The optional Claude path was exercised only with a scripted model.
