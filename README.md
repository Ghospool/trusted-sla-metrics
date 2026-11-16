# From Support Tickets to Trusted SLA Metrics

A portfolio project demonstrating a repeatable operational analytics process, with entirely fictional support data. No employer tickets, names, policies, or infrastructure are used.

**Portfolio message:** I can automate a repeatable operational analytics process and make its metrics trustworthy.

## Delivery status

Stage 1 contains a seeded Python generator, CSV quality/lifecycle validation, a PostgreSQL loader, raw/staging/analytics SQL, an offline metric oracle, sample inputs, expected outputs, and a failed-load/correction/replay demonstration.

The offline demo runs without third-party Python packages. Live PostgreSQL integration and the original KNIME archive were verified locally as described in [VERIFICATION.md](VERIFICATION.md). This package contains `knime/Trusted_SLA_Metrics_Public.knwf`, with personal author metadata replaced and its optional embedded preview omitted. That exact archive was separately re-imported and freshly executed locally, with all eight nodes saved as executed and fresh CSV run IDs verified.

## Quick start

Use Python 3.11 or newer. Run commands from this directory. Windows users can substitute `py` for `python`.

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m sla_pipeline validate --input data/sample
.venv\Scripts\python -m sla_pipeline demo --input data/sample --output build/demo
.venv\Scripts\python -m unittest discover -s tests -v
```

On macOS/Linux use `.venv/bin/python` in place of `.venv\Scripts\python`.

For a no-install, standard-library-only Windows demo, use `$env:PYTHONPATH = 'src'` followed by `py -m sla_pipeline demo --input data/sample --output build/demo` from this directory. This does not install the PostgreSQL driver.

The demo deliberately tries a bad priority, corrects it, then replays the corrected batch. Inspect `build/demo/run_log.json` and `build/demo/ticket_metrics.csv`. The failed batch has zero inserts/updates. The corrected run loads the batch. The replay inserts and updates zero records. This is an **offline simulation of loader behavior**, not evidence that PostgreSQL or KNIME executed.

Generate a larger reproducible dataset:

```powershell
.venv\Scripts\python -m sla_pipeline generate --output build/generated --seed 42 --tickets 1000
.venv\Scripts\python -m sla_pipeline validate --input build/generated
```

Generation uses a fixed historical time window, not the machine clock. Keep `--seed`, `--tickets`, and generator version fixed to reproduce bytes. Treat generated directories as disposable: generation replaces the four CSVs at the chosen destination.

## PostgreSQL run

Use a dedicated empty portfolio database on PostgreSQL 14 or newer and a role allowed to create schemas/tables/functions. Never point this demo at a production database. Do not commit passwords or connection URLs.

```powershell
.venv\Scripts\python -m pip install -e ".[postgres]"
$env:DATABASE_URL = 'postgresql://YOUR_USER:YOUR_PASSWORD@localhost:5432/YOUR_DEMO_DB'
.venv\Scripts\python -m sla_pipeline init-db
.venv\Scripts\python -m sla_pipeline load --input data/sample
.venv\Scripts\python -m sla_pipeline load --input data/sample
.venv\Scripts\python -m sla_pipeline metrics --output build/postgres_metrics.csv
```

To demonstrate rejection and correction in PostgreSQL after the base sample load:

```powershell
# Expected failure: P9 is not a supported priority; canonical data stays unchanged.
.venv\Scripts\python -m sla_pipeline load --input data/sample/invalid_batch
# Corrected ticket BAD001 and events now load; a second identical call is unchanged.
.venv\Scripts\python -m sla_pipeline load --input data/sample/corrected_batch
.venv\Scripts\python -m sla_pipeline load --input data/sample/corrected_batch
# Two late status events revise beacon_desk/T004 resolution time from 60 to 40 minutes.
.venv\Scripts\python -m sla_pipeline load --input data/sample/late_event_batch
.venv\Scripts\python -m sla_pipeline metrics --output build/postgres_after_late.csv
```

`data/expected/sample_metrics.csv` applies before supplemental loads; `after_late_arrival_metrics.csv` applies to the original nine tickets after the late events, and `corrected_batch_metrics.csv` describes the additional corrected ticket. Expected files include their cutoff and use `status` for the SQL output's `current_status` column. They intentionally omit team/priority attributes and compare metric values, not CSV byte formatting.

Create `build/` first if you did not run the offline demo. `DATABASE_URL` is read at runtime and not written to project files. Shell history can retain values entered directly: for real credentials prefer setting the environment through your approved credential tooling.

`init-db` executes `sql/001_schema.sql` and `sql/002_metrics.sql`. It is safe to repeat for this version; it is not a schema migration system. Review `sql/003_quality_checks.sql` for database reconciliation queries.

Database integration tests are opt-in. Create a separate **empty disposable database**, install the PostgreSQL extra, and run:

```powershell
$env:TEST_DATABASE_URL = 'postgresql://YOUR_USER:YOUR_PASSWORD@localhost:5432/YOUR_EMPTY_TEST_DB'
$env:SLA_TEST_ALLOW_RESET = '1'
.venv\Scripts\python -m unittest discover -s tests -p test_postgres_integration.py -v
```

Despite the acknowledgment variable's name, the test does not drop schemas or reset a database: it refuses pre-existing project objects and leaves created test evidence behind. Use a fresh disposable database for a subsequent full integration run. Its URL must differ from the configured application `DATABASE_URL`. Missing driver/database/setup produces an explicit skip; a skip does not count as PostgreSQL verification.

## KNIME run

The final workflow uses KNIME 5.12.0 LTS with matching Python Integration, a separate Python 3.12 environment, and this project editable-installed with `.[postgres]`. It shares the Python validation/atomic loader and parameterized PostgreSQL metrics query; JDBC credentials and per-table DB Writers are not used.

Save and close all KNIME windows, then use Command Prompt from this project directory:

```bat
"C:\Tools\Miniforge3\envs\trusted-sla-knime\python.exe" scripts\launch_knime.py
```

The hidden prompt supplies a password only to KNIME's process environment and descendants. It is not a credential vault; close those processes when finished. The launcher targets the existing local `trusted_sla_demo` database and does not initialize or load it. Import `knime/Trusted_SLA_Metrics_Public.knwf` into a new local workflow group only after preparing the database as described in the [KNIME guide](knime/README.md).

The workflow checks 81 baseline golden values offline, replays the retained late-event batch, queries ten database tickets, and demonstrates a rejected batch with no partial canonical changes. The public archive's fresh outputs and provenance are under `knime/evidence/public-reimport/`; `knime/evidence/reimport/` retains the original archive's earlier evidence. The full project checkout and prepared local database remain external runtime dependencies of the `.knwf`.

## Data flow

```text
Seeded fictional CSVs
        |
        v
raw.pipeline_runs + raw.records (durable intake lineage)
        |
        v
Schema / values / references / complete lifecycle validation
        |                              |
        | any rejection                | all valid
        v                              v
raw.rejected_records          atomic staging upserts
no canonical changes          teams / policies / tickets / events
                                       |
                                       v
                         analytics.ticket_metrics(as_of)
```

The Python loader owns the atomic transaction. KNIME is a visual orchestration entry point using that same contract and load rules, not a second, inconsistent definition of SLA metrics.

## Metric rules

| Concern | Rule |
| --- | --- |
| Time | UTC, 24/7 elapsed time; no business-hours or holiday calendar |
| First response | Minutes from ticket creation to earliest `responded` event; never reset by reopening |
| Response clock | Calendar time; requester-wait does not pause it |
| Resolution clock | Cumulative minutes in `open`; excludes `waiting` and `resolved` intervals |
| Reopening | `resolved` to `open`; resumes cumulative resolution time, increments reopen count |
| Unresolved tickets | Resolution exposure measured through explicit `as_of`; breach can already be true |
| SLA boundary | Strictly greater than target is a breach; exact equality is not |
| Precision | Python accumulates exact microsecond timedeltas and converts to decimal minutes; PostgreSQL uses interval/numeric arithmetic |
| Missing response | Response duration is null; response breach uses age through `as_of`, even if already resolved |
| Backlog age | Calendar minutes since creation for `open`/`waiting`; null when resolved |
| Historical cutoff | Exclude tickets and events later than `as_of` |
| Tied events | Same timestamp ordered by event ID, case-sensitive lexical order |
| Late arrival | Existing event history plus incoming events is revalidated; querying metrics recalculates the result |
| Policy selection | Current priority and current static SLA targets; policy/priority history is out of scope |
| Staffing | Static team headcount attribute; no shifts, utilization, or productivity attribution |

Allowed state transitions:

```text
open --waiting--> waiting --resumed--> open --resolved--> resolved
  ^                                                        |
  +----------------------- reopened -----------------------+
```

A `responded` event leaves `open` unchanged. Repeated response events are allowed while open; only the earliest determines first response. Resolving while waiting requires a preceding `resumed` event. Events cannot precede creation or exceed the load's cutoff. Historical metric queries may use an earlier cutoff than ingestion.

## Input and quality contract

Four UTF-8 CSVs with exact ordered headers are required for every batch. Incremental batches may contain header-only files for unchanged entities.

- `teams.csv`: `team_id,team_name,staffing_count`
- `policies.csv`: `priority,response_target_minutes,resolution_target_minutes`
- `tickets.csv`: `source_system,ticket_id,created_at,priority,team_id,subject`
- `events.csv`: `source_system,event_id,ticket_id,occurred_at,event_type`

Blank fields, surrounding whitespace, malformed timestamps, non-UTC timestamps, unknown references, invalid priorities, non-positive/nonfinite targets, staffing outside PostgreSQL's nonnegative integer range (0–2,147,483,647), duplicate keys within a file, and impossible lifecycle sequences are rejected. Naive timestamps are never silently interpreted as local time. Rejection row numbers are logical CSV record positions with the header counted as row 1, not physical line offsets in multiline quoted fields. A small rejected-records example is committed at `data/expected/invalid_batch_rejections.csv`.

Ticket identity is `(source_system, ticket_id)`; event identity is `(source_system, event_id)`. Identical input across runs is unchanged, not duplicated. Corrections to existing records are counted as updates. An event's existing ticket assignment cannot be changed. No delete/tombstone semantics are implemented. Overlapping ticket IDs from different sources stay separate.

A batch with any rejected row **fails as a whole**: raw intake and rejection reasons remain, but canonical tables stay unchanged. `accepted` means rows that passed checks, not rows committed. On a rejected batch `inserted`, `updated`, and `unchanged` are all zero. On success their sum equals `accepted`. On every validated batch `received = accepted + rejected`. CSV header/file errors occur before database intake and return a nonzero CLI result; they do not create row-level run logs.

Database loads serialize through a PostgreSQL advisory transaction lock so concurrent instances of this loader cannot validate against stale canonical history. External writers bypassing this loader are out of scope. Unexpected database failures roll back canonical changes and mark the run failed; if the database itself is unavailable, a run can remain `running` and requires operator reconciliation. Intake is intentionally retained for audit, including exact replays.

## Repository map

- `src/sla_pipeline/`: generator, shared contract, independent Python metric oracle, PostgreSQL adapter, CLI.
- `sql/`: database DDL, canonical analytics function, quality/audit queries.
- `data/sample/`: small fictional inputs and supplemental examples.
- `data/expected/`: hand-calculated outputs for the fixed sample cutoff.
- `tests/`: public-behavior checks and optional database integration.
- `knime/Trusted_SLA_Metrics_Public.knwf`: sanitized exported workflow, separately re-imported and freshly executed locally.
- `knime/evidence/public-reimport/`: fresh evidence and provenance for the sanitized public archive.
- `knime/README.md`: runtime prerequisites, session-only authentication, node layout, and import/execution instructions.
- `knime/evidence/reimport/`: historical metrics, rejection evidence, and provenance for the original archive's earlier re-import.
- `scripts/`: session-only KNIME launcher and expected-rejection verification helper.
- `VERIFICATION.md`: what was actually executed versus what remains unverified.

## Demonstration walkthrough

1. Explain the grain, identities, and SLA rules above.
2. Show the fixed-seed generator and the readable small sample.
3. Run validation, the offline failure/correction/replay demo, and behavioral tests.
4. With PostgreSQL available, show raw records, rejection reasons, run counters, idempotent replay, and SQL metrics matching expected results.
5. Demonstrate a late-arriving event and a reopened ticket changing resolution exposure correctly.
6. Import the executable KNIME `.knwf` into a new local workflow group, execute it, and show fresh run IDs in the generated metrics and rejected-batch evidence. Separate-group re-import was verified locally; a clean independently configured workspace remains untested.

Do not claim business impact from simulated records, or claim unexecuted integrations work. The project demonstrates engineering choices and verifiable calculations, not an employer case study.

## License

Project code and documentation are offered under the [MIT License](LICENSE), copyright 2026 Ghospool. Python, PostgreSQL, KNIME, and other third-party dependencies retain their own licenses and are not redistributed as installed environments or application binaries.

The original export is not included. The public archive replaces personal author/editor metadata with Ghospool and omits the embedded preview assets. That exact archive has its own fresh local re-import verification under `knime/evidence/public-reimport/`; the original archive's verification is historical context, not a substitute.
