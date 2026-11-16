# Verification record

## Public archive status

This repository contains `knime/Trusted_SLA_Metrics_Public.knwf`, a separate derivative with author/editor metadata replaced by Ghospool and its optional SVG preview omitted. That exact archive has its own fresh local re-import verification, detailed under "Sanitized public archive re-import" below. The original export is not distributed here, and its older execution evidence remains historical context only.

This file distinguishes observed local results from integrations that still need execution. All data are fictional. Reproducible metric cutoff: `2025-01-08T00:00:00Z`.

## Observed local results

- Python 3.12.10 is present through the Windows `py` launcher.
- Initial behavioral suite: `py -m unittest discover -s tests -v` printed `Ran 35 tests in 3.388s` and `OK (skipped=1)`: 34 passed, one PostgreSQL integration test initially skipped for missing opt-in database configuration. All three CLI subprocess tests passed, including expected process exit codes 0, 1, and 2. The later live-database result is recorded below.
- Regression coverage includes fractional-second exact SLA equality, one-microsecond-over breaches, paused fractional intervals, PostgreSQL staffing integer boundaries, entity-mapping order, and the committed rejection example. The live integration sequence also covers database-session UTC configuration and fractional-second SQL thresholds.
- CLI help executed and displayed generation, validation, demo, database initialization, load, and metrics commands.
- Sample validation reported 41 received, 41 accepted, and zero rejected records across the four inputs.
- Offline failed-load demo reported 41 received, 38 accepted, three rejected, and zero inserted/updated records. Rejections include dependent events referencing the invalid new ticket.
- Corrected offline load reported 41 inserts; identical replay reported zero inserts, zero updates, and 41 unchanged records.
- An independent JavaScript CSV comparison found zero mismatches between all nine demo tickets and their hand-calculated expected metric values. It also checked the persisted run-log counters.
- The fixed-seed 1,000-ticket generation smoke run produced a batch of 4,335 records including dimensions/events; Python validation reported all 4,335 accepted and no rejections.
- The generator worker reported checking deterministic byte equality, 24 seed/count combinations, valid lifecycle sequences, UTC cutoff, overlapping source IDs, expected fixtures, and invalid/corrected/late batches; it printed its PASS marker.
- SQL DDL/function contract checks and an independent static SQL review found no concrete issues. Static review is not a database execution test.
- A separate source review found non-UTC-session, fractional-arithmetic, and staffing-range bugs; these were corrected and regression coverage added. A requested independent post-fix re-review timed out after 300 seconds, so there is no completed independent post-fix sign-off.
- Subsequent installed-package check: the user created `.venv` with Python 3.12.10 and installed the project plus the PostgreSQL extra. `pip check` reports no broken requirements. The same CLI runs successfully through Command Prompt.
- Installed-environment suite through `cmd.exe /d /c`: `.venv\Scripts\python.exe -m unittest discover -s tests -v` printed `Ran 35 tests in 2.535s`, `OK (skipped=1)`, and an explicit successful child-process status with no trailing access-denied error. This verifies 34 passing tests and one intentionally skipped PostgreSQL integration test in the installed environment.
- User screenshots confirm a newly initialized PostgreSQL 15 instance, a successful pgAdmin connection, and separate `trusted_sla_demo` / `trusted_sla_test` databases.

## Live PostgreSQL verification

The user's Command Prompt screenshots show PostgreSQL **15.13** and the configured full suite finishing with **`Ran 35 tests in 9.315s` / `OK`**, with no skips. In particular, `test_disposable_database_public_load_and_metrics_sequence` reports `ok` rather than skipped.

That integration sequence checks schema/function initialization, database metrics against the hand-calculated fixtures, raw/rejection audit counts, canonical rollback on rejected batches, idempotent replay, historical cutoffs, late events, corrections, invalid event reassignment, non-UTC connection settings, and fractional-second SLA thresholds in `trusted_sla_test`.

This is screenshot evidence of a local run, not an independent rerun against the database. The password was entered locally and is not stored in the project. The integration test intentionally retains its database objects and records: do not rerun it against the occupied test database expecting a fresh run.

## Live demo walkthrough

Subsequent user screenshots verify these results in `trusted_sla_demo`, separately from the integration-test database:

| Run | Status | Received | Accepted | Rejected | Inserted | Updated | Unchanged |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Original sample | succeeded | 41 | 41 | 0 | 41 | 0 | 0 |
| Identical sample replay | succeeded | 41 | 41 | 0 | 0 | 0 | 41 |
| Invalid batch | failed | 10 | 7 | 3 | 0 | 0 | 0 |
| Corrected batch | succeeded | 10 | 10 | 0 | 3 | 0 | 7 |
| Late-event batch | succeeded | 10 | 10 | 0 | 2 | 0 | 8 |
| Identical late-event replay | succeeded | 10 | 10 | 0 | 0 | 0 | 10 |

The four runs were also visible together in a pgAdmin query of `raw.pipeline_runs`. A separate query of `raw.rejected_records` returned the retained ticket-row-2 `unknown priority` rejection and event-row-2 / event-row-3 `unknown ticket for source_system` rejections after correction succeeded. Accepted counts are validation results, not committed rows: the failed run has zero inserted, updated, and unchanged records.

The baseline pgAdmin metrics query returned nine tickets at `2025-01-08T00:00:00Z`. Visible checks included `atlas_service / T001` at 15 response / 60 resolution minutes without breaches, and reopened `atlas_service / T002` at 300 resolution minutes with a resolution breach. After late-event loading, the user's filtered pgAdmin query showed `beacon_desk / T004` still resolved, first response 10 minutes, resolution **40 minutes** (previously 60), and no resolution breach. A repeated metric screenshot still showed 40 minutes. The subsequent Command Prompt screenshot includes both the late-event load and its successful replay counters as recorded in the table above.

The late-event batch contains ten records: three teams, four policies, one existing ticket, and two new events. Initial load inserts only the two events and reports eight unchanged records; replay reports all ten unchanged.
These are screenshot-observed results; the screenshots are not included as a separately exported evidence bundle.

## Executable KNIME workflow and re-import

The user built and executed the workflow in **KNIME Analytics Platform 5.12.0 LTS**, using non-legacy **KNIME Python Integration 5.12.0** and a separate Conda environment with **Python 3.12.16 / psycopg 3.3.9**. The existing project `.venv` was preserved. The initially mixed KNIME 5.4/5.12 installation was resolved by the user upgrading to the consistent 5.12 LTS platform/extensions; no forced extension downgrade or security-policy change was used.

The final eight-node workflow uses the shared Python contract, atomic PostgreSQL adapter, and parameterized SQL metrics function. The earlier JDBC branch was removed. A hidden-password launcher supplies session-only `PGPASSWORD` and a password-free `DATABASE_URL` to a new KNIME process; no password is stored in the workflow, ordinary flow variables, or evidence files. The user successfully launched KNIME and its Python connection check returned `trusted_sla_demo`, `postgres`, `UTC`, and `PASS`. The password remains process-environment data, not a credential vault.

Observed original-workflow checks:

- Standalone original-sample validation: 41 received/accepted, zero rejected; nine tickets and 81 golden values matched, without database writes.
- Atomic late-event replay: 10 received/accepted/unchanged, zero rejected/inserted/updated.
- SQL metrics: ten tickets at the fixed cutoff, including `beacon_desk / T004` at 10 first-response and 40 resolution minutes.
- Expected-failure check: a new fictional source identity avoids the retained corrected ticket; a valid new team probes whole-batch rejection. Eleven received, eight accepted, three rejected, and zero inserted/updated/unchanged. The helper compares all canonical tables before/after and checks persisted raw intake, run counters, rejection payloads, and reasons. All three output rows show `check_result=PASS`, `load_status=failed`, `canonical_unchanged=true`, and `valid_probe_team_absent=true`.
- Workflow-relative CSV Writers emitted `data/sla_metrics.csv` and `data/rejected_batch_evidence.csv`; booleans are represented as `1`/`0` in these CSVs. Repeated counters on rejection rows are run totals, not additive row counts.

### Export inspection

Artifact: `knime/Trusted_SLA_Metrics.knwf`, **62,611 bytes**. SHA-256:

```text
be7b0ec346a6f34f98286ad4cf5637fb5d6e2f8ddba85e58f34012a92a7649db
```

Archive inspection found an intact ZIP, both historical evidence CSVs, eight node settings, five compilable Python scripts, workflow-relative output destinations, no cached node result tables, and no stored credentials or machine-specific paths in the inspected settings/scripts. Original CSV run IDs are `d57ab0b4-7e31-458b-a892-4db138142e89` (metrics) and `6f8e6d0c-71ba-45d2-a81c-d3e2d5175feb` (expected failure). An offline comparison of the metrics CSV against the Python oracle, after preparing the base/corrected/late fixtures in memory, matched **110 field values across ten tickets**, with the cutoff checked separately. Rejection reasons, payloads, run totals, unchanged flags, and run ID separation also matched.

The first inspection harness needed namespace-aware XML parsing; its corrected run printed all expected check markers. Automated Python child processes still reported exit status `-1` despite those markers, so this is not a clean process-exit claim. Independent in-process JavaScript archive/filesystem assertions returned successfully. Neither archive inspection nor evidence comparison opened a database connection or executed the exported node scripts.

### Fresh re-import execution

The user imported the archive into `SLA_Reimport_Check/KNIME_Personal_Project_run`, a separate group in the **same local KNIME workspace**. Reset was disabled because no cached results were loaded. All nodes were executed with an all-green result. File inspection subsequently confirmed all eight saved node settings as `EXECUTED`, with no machine-specific paths, and checked the newly generated CSVs:

| Evidence | Fresh run ID | Rows |
| --- | --- | --- |
| Metrics | `f0692e48-10fb-4b91-9b16-3cdd337ca847` | 10 |
| Expected-failure rejections | `2c16d5ea-3c0a-4b95-bd28-753353e86828` | 3 |

Both run IDs differ from the archive's historical CSVs. The fresh metrics equal the exported metrics in every field except `run_id`; `beacon_desk / T004` remains at 40 resolution minutes. The fresh rejection output again has the expected three reasons and 11/8/3 counters, zero canonical-change counters, and true unchanged/probe-absence flags.

Fresh CSVs were retained byte-for-byte under `knime/evidence/reimport/`, alongside `verification.json` with their hashes, original/fresh run IDs, runtime evidence scope, archive checksum, and hashes of 31 external project dependencies. The workflow resolves fixtures/helper code through the editable-installed project. It is not a self-contained Python/PostgreSQL distribution.

The original corrected-batch inserts and initial 60-to-40-minute late-event mutation were verified in the CLI/pgAdmin walkthrough above. The KNIME artifact verifies the evolved result, replay, and a fresh rejected-batch check; it did not destructively replay those first mutations. A new machine and an independently configured KNIME workspace were not tested.

## Sanitized public archive re-import

The separately prepared `knime/Trusted_SLA_Metrics_Public.knwf` is 15,187 bytes, SHA-256 `dc958c555a86d629a76e5a35e67b5c35481eb39a018bcc7a138d554a6d45370e`. Its author/editor fields use Ghospool, and the optional SVG preview with embedded font/icon assets is omitted. The original export is preserved outside this package; it was not silently replaced or re-exported.

After resolving a missing launcher environment and starting the existing local PostgreSQL instance, the user executed the public archive's imported copy under `SLA_Public_Release_Check` and saved it. File inspection confirmed all eight nodes as `EXECUTED`, all five Python scripts unchanged from the sanitized archive, both CSV Writers still workflow-relative, and all 31 recorded external dependency hashes unchanged. The inspection itself ran no database queries or node executions.

- Metrics: ten rows, fresh run `1a0396bf-b6f6-4856-82d8-847b5bbfc706`; every non-run-ID field matches the prior verified CSV, including cutoff and T004 resolution at 40 minutes.
- Expected-failure evidence: three rows, fresh run `81dec695-5cd9-4579-91e4-12bdc77fa737`; 11 received, eight accepted, three rejected, zero inserted/updated/unchanged, all PASS/failed-load/unchanged/probe-absence checks preserved. Rejection reasons and payloads match apart from the deliberately fresh fictional source identity.
- Both run IDs differ from the earlier re-import outputs and the archive's bundled historical CSVs. Fresh files and their hashes are retained under `knime/evidence/public-reimport/`.

This verifies the exact sanitized input archive through a separate group on the same machine and local KNIME workspace. It is not a clean-machine test or a new full automated test-suite run.

## Not yet verified

- A separately retained portable capture of the earlier CLI/pgAdmin first-correction and initial late-event-mutation walkthrough. Those steps remain screenshot-observed; the KNIME archive and fresh re-import CSV evidence are retained as described above.
- A new-machine installation or independently configured clean KNIME workspace. Separate-group re-import and fresh execution on this machine are verified.
- Load/performance benchmarks or concurrent external database writers.
- Mutation testing.

## Completion gates

1. Installed-package behavioral verification completed through Command Prompt. The subsequent full suite against PostgreSQL passed all 35 tests without skips.
2. Live PostgreSQL integration completed in `trusted_sla_test`; retain its raw intake/rejections, run counters, canonical rows, and metric evidence. Any future full integration rerun requires a fresh disposable database rather than overwriting retained evidence.
3. Database demo walkthrough verified by user screenshots, including late-event counter/replay evidence. KNIME metrics/rejection CSV evidence is now retained separately. Do not reload the original sample to reproduce the baseline in this populated database: later events and the corrected ticket are intentionally retained.
4. KNIME workflow built/exported, inspected, re-imported into a separate group in the same local workspace, and freshly executed. Runtime/extension versions, archive checksum, and fresh run IDs are recorded above. Independent clean-workspace/new-machine portability remains untested.
5. Project code/documentation are MIT licensed; `LICENSE` records copyright 2026 Ghospool. The public copy replaces personal author metadata and omits embedded font/icon preview assets; its own fresh re-import check is complete as recorded above.
