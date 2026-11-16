# KNIME workflow

`Trusted_SLA_Metrics_Public.knwf` is derived from the locally verified KNIME 5.12.0 LTS export. Its two personal author/editor fields use Ghospool, and `workflow.svg` is omitted to avoid redistributing embedded font/icon preview assets. That exact archive was separately re-imported, freshly executed, saved, and inspected locally. All eight nodes are executed, all five Python scripts match the archive, and both CSVs have fresh run IDs. Evidence is under `evidence/public-reimport/`; older evidence under `evidence/reimport/` describes the original export, which is not included here.

Public archive SHA-256:

```text
dc958c555a86d629a76e5a35e67b5c35481eb39a018bcc7a138d554a6d45370e
```

All inputs and outputs are fictional. No database password is stored in the archive. The workflow uses the existing Python PostgreSQL adapter rather than JDBC credential nodes or independent per-table DB Writers.

## Deliverables

- `evidence/public-reimport/`: fresh ten-row metrics, three-row expected-rejection evidence, and a manifest for this exact sanitized archive.

- `Trusted_SLA_Metrics_Public.knwf`: exported workflow, without cached node result tables; includes the original demonstration CSVs in its `data` area.
- `evidence/reimport/sla_metrics.csv`: freshly generated re-import metrics, ten tickets.
- `evidence/reimport/rejected_batch_evidence.csv`: three persisted rejection rows from the fresh expected-failure check.
- `evidence/reimport/verification.json`: archive checksum, original/fresh run IDs, output hashes, verification scope, and hashes of 31 external project dependencies.
- `../scripts/launch_knime.py`: Windows session-only hidden-password launcher.
- `../scripts/knime_rejection_check.py`: expected-failure check used by Node 9.

Original locally verified archive SHA-256 (not the public archive):

```text
be7b0ec346a6f34f98286ad4cf5637fb5d6e2f8ddba85e58f34012a92a7649db
```

The fresh companion CSVs have different run IDs from the historical CSVs packaged in the archive. Re-execution replaces generated CSVs in that imported workflow's data area, not these retained project evidence files.

## Prerequisites

1. KNIME Analytics Platform 5.12.0 LTS with non-legacy KNIME Python Integration 5.12.0. The database/JDBC extension is not used by this final workflow.
2. A manual KNIME Python environment containing `knime-python-scripting=5.12.0`, pandas, and this project editable-installed with its PostgreSQL extra. Tested: Python 3.12.16 and psycopg 3.3.9 in a separate `trusted-sla-knime` Conda environment. Keep the project's original `.venv` separate.
3. The full project checkout, including `src/`, `data/`, and `scripts/`. Nodes discover it through `sla_pipeline.__file__`; a wheel-only installation without fixtures/helper scripts is insufficient. The `.knwf` does not bundle Python, the project checkout, or PostgreSQL.
4. Local PostgreSQL on `127.0.0.1:5432`, database `trusted_sla_demo`, role `postgres`, with the project schema/functions and prepared demo state. PostgreSQL 15.13 was tested. The launcher and rejection check deliberately target this local demonstration setup.
5. A prepared database containing the base sample, corrected supplemental batch, and late-event batch. The expected current database has ten tickets. Follow the root README's PostgreSQL initialization/load sequence only for a fresh database. Do not reload the original sample over the retained evolved demo merely to reproduce its nine-ticket baseline.

The fixed cutoff is `2025-01-08T00:00:00Z`, imported as `sla_pipeline.model.AS_OF`. There is no general-purpose GUI input-directory or cutoff selector in this version.

## Session-only authentication

Save and close all KNIME windows normally. From Command Prompt in the project directory, use the tested Python environment:

```bat
"C:\Tools\Miniforge3\envs\trusted-sla-knime\python.exe" scripts\launch_knime.py
```

Enter the PostgreSQL password only at the hidden local prompt. The launcher checks for an existing KNIME process before prompting and again before launching. It supplies a password-free `DATABASE_URL` and session `PGPASSWORD` to the new KNIME process. It performs no database loads itself.

The default executable is `C:\Program Files\KNIME\knime.exe`; the default workspace is the current user's `knime-workspace`. Use `--knime` or `--workspace` for another existing installation/workspace. `--check` checks paths/processes without prompting or launching. Missing paths, inaccessible process checks, unavailable hidden input, empty passwords, and detected running KNIME processes stop the launcher.

The password is not put in command arguments, ordinary flow variables, workflow settings, or evidence files. It remains available in KNIME's process environment and to its descendants/process-inspection tools: this is not a credential vault. Close KNIME and its child processes to end the session. The launcher does not erase an independently pre-existing password from its parent shell environment. Do not print environment variables to troubleshoot credentials.

## Workflow layout

```text
Table Creator #2
  |-- Python #1: standalone sample validation + golden check
  |
  `-- Python #6: read-only database connection check
        |-- Python #7: atomic late-batch replay
        |     `-- Python #8: SQL metrics after successful load
        |           `-- CSV Writer #10: data/sla_metrics.csv
        |
        `-- Python #9: expected rejected-batch/atomicity check
              `-- CSV Writer #11: data/rejected_batch_evidence.csv
```

| Node | Behavior |
| --- | --- |
| 2 | Supplies the input table required by Python Script nodes; it contains no credentials. |
| 1 | Validates the original nine-ticket sample offline and compares 81 golden metric values. It does not query or reset the evolved database. |
| 6 | Reads the database name, user, and UTC session setting without outputting a password. |
| 7 | Calls `postgres.load` on `data/sample/late_event_batch`; on the prepared database, reports 10 received/accepted/unchanged and zero inserts/updates/rejections. Every execution adds raw audit lineage. |
| 8 | Requires a single successful loader summary, then calls `query_metrics(AS_OF)`, which parameterizes the SQL function call. Adds the successful `run_id` and cutoff to the output. Decimal durations are converted to numeric KNIME display columns; the SQL calculation remains numeric/interval-based. |
| 9 | Reads the invalid fixture, gives its ticket/events fresh fictional source identities, and adds a valid new team as a no-partial-commit probe. Checks the local database endpoint, preflights expected rejection, loads, compares all canonical tables before/after, and reads back persisted run/intake/rejection evidence. |
| 10, 11 | Write headers and no RowIDs; overwrite only their generated workflow-relative CSV outputs. |

Node 9 must produce `check_result=PASS` while `load_status=failed`: rejection is the expected result. It must show **11 received, 8 accepted, 3 rejected**, with zero inserted/updated/unchanged, `canonical_unchanged=true`, and `valid_probe_team_absent=true`. Eight accepted rows are validation results, not committed rows. The counters repeat on each of three rejection rows; do not sum them.

A new source identity on each expected-failure execution prevents the earlier corrected `BAD001` from satisfying the invalid fixture's event references. All such runs fail atomically; only raw/audit data accumulate. The valid probe team must never be inserted. Rejection reasons are `unknown priority` for ticket record 2 and `unknown ticket for source_system` for event records 2 and 3. Record positions count the CSV header as row 1.

## Import and execute

1. Start KNIME using the session-only launcher and verify the configured manual Python environment.
2. Import `Trusted_SLA_Metrics_Public.knwf` into a new local workflow group. Do not overwrite an existing workflow; the public archive's verified group was `SLA_Public_Release_Check`.
3. Open the imported copy. It has no cached result tables. If Reset is disabled, there are no executed results to clear; do not change node settings merely to enable Reset.
4. Select all nodes and execute. This adds one successful replay audit run and one expected-failure audit run; no canonical changes are expected on the prepared database. Do not run external canonical writers concurrently with the before/after check.
5. Confirm all eight nodes execute, the golden check passes, metrics contain ten tickets, and `beacon_desk / T004` remains resolved with 40 resolution minutes and 10 first-response minutes.
6. Check the three expected-failure output rows and both CSVs in the imported workflow's `data` folder. Their run IDs must be fresh, not the IDs from the packaged historical CSVs.
7. Save the imported workflow, but do not export over the verified public archive. A new export can reintroduce personal metadata and embedded preview assets; sanitize it separately and repeat the fresh re-import check against its new checksum before distribution.

If a node fails, inspect its error before rerunning. Do not reinitialize or reset the database, weaken authentication, persist a password, or load the original sample as a shortcut.

## Verification scope and remaining work

The original archive and retained fresh CSVs were inspected; metrics matched the independent Python oracle across 110 field values for ten tickets, and all eight imported nodes were saved as executed. Exact run IDs and hashes are in the evidence manifest and `../VERIFICATION.md`.

The CLI/PostgreSQL walkthrough separately verified the first corrected-batch insert and the original late-event change from 60 to 40 minutes. Both locally verified KNIME versions reproduce the retained result, idempotent late-batch replay, and a fresh rejected-batch atomicity check; neither re-creates those first successful mutations against the populated database. A new-machine installation, independently configured KNIME workspace, production deployment, and load benchmark remain outside the completed local execution evidence. Project code/documentation are MIT licensed; dependencies retain their own licenses. The public archive omits the original preview assets and has its own fresh verification.
