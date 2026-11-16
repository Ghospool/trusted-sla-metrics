"""Expected-failure KNIME check; persist audit evidence but no canonical changes."""

import json
from pathlib import Path
from uuid import uuid4

from sla_pipeline.model import AS_OF, prepare, read_batch
from sla_pipeline.postgres import connect, load, snapshot


def check_rejection(project_dir):
    batch = read_batch(Path(project_dir) / "data" / "sample" / "invalid_batch")
    namespace = "knime_reject_" + uuid4().hex
    for entity in ("tickets", "events"):
        for row in batch[entity]:
            row["source_system"] = namespace
    batch["teams"].append({
        "team_id": namespace,
        "team_name": "Fictional KNIME atomic rollback probe",
        "staffing_count": "1",
    })

    with connect() as connection:
        if (connection.info.hostaddr != "127.0.0.1" or connection.info.port != 5432
                or connection.info.dbname != "trusted_sla_demo"):
            raise ValueError("This check requires trusted_sla_demo on 127.0.0.1:5432.")
        before = snapshot(connection)

    _, projected_rejections, projected = prepare(batch, before, AS_OF)
    expected_counts = {"received": 11, "accepted": 8, "rejected": 3,
                       "inserted": 0, "updated": 0, "unchanged": 0}
    expected_reasons = sorted([
        ("tickets", 2, "unknown priority"),
        ("events", 2, "unknown ticket for source_system"),
        ("events", 3, "unknown ticket for source_system"),
    ])
    if projected != expected_counts or sorted(
        (row["entity"], row["row_number"], row["reason"]) for row in projected_rejections
    ) != expected_reasons:
        raise ValueError("Unexpected preflight result; no database load attempted.")
    if (namespace,) in before["teams"]:
        raise ValueError("Probe identity already exists; no database load attempted.")

    result = load(batch, AS_OF)
    with connect() as connection:
        after = snapshot(connection)
        stored_run = connection.execute(
            "SELECT status, records_received, records_accepted, records_rejected, "
            "records_inserted, records_updated, records_unchanged "
            "FROM raw.pipeline_runs WHERE run_id = %s", (result["run_id"],)
        ).fetchone()
        intake_count = connection.execute(
            "SELECT count(*) FROM raw.records WHERE run_id = %s", (result["run_id"],)
        ).fetchone()[0]
        persisted = list(connection.execute(
            "SELECT entity, row_number, payload, reason FROM raw.rejected_records "
            "WHERE run_id = %s ORDER BY entity, row_number", (result["run_id"],)
        ))

    if before != after:
        raise ValueError("FAIL: canonical data changed during an expected rejected load. Stop and inspect the run.")
    if result["status"] != "failed" or any(result[key] != value for key, value in expected_counts.items()):
        raise ValueError("FAIL: unexpected loader status or counters; inspect raw.pipeline_runs.")
    if stored_run != ("failed", 11, 8, 3, 0, 0, 0) or intake_count != 11:
        raise ValueError("FAIL: persisted run counters or raw intake do not reconcile.")
    expected_persisted = sorted(
        [(row["entity"], row["row_number"], row["payload"], row["reason"])
         for row in result["rejections"]], key=lambda row: (row[0], row[1])
    )
    if persisted != expected_persisted or sorted(
        (entity, number, reason) for entity, number, _, reason in persisted
    ) != expected_reasons:
        raise ValueError("FAIL: persisted rejection evidence does not match the failed load.")

    return [{
        "check_result": "PASS",
        "load_status": result["status"],
        "run_id": result["run_id"],
        "as_of": AS_OF,
        "canonical_unchanged": True,
        "valid_probe_team_absent": (namespace,) not in after["teams"],
        **expected_counts,
        "entity": entity,
        "row_number": number,
        "reason": reason,
        "payload_json": json.dumps(payload, sort_keys=True),
    } for entity, number, payload, reason in persisted]


if __name__ == "__main__":
    import pandas as pd
    import knime.scripting.io as knio

    rows = check_rejection(Path(__file__).resolve().parents[1])
    knio.output_tables[0] = knio.Table.from_pandas(pd.DataFrame(rows))
