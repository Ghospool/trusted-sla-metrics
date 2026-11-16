"""PostgreSQL adapter. Credentials come only from DATABASE_URL."""

import os
from pathlib import Path
from uuid import uuid4

from .model import FIELDS, KEYS, empty_state, equivalent, identity, prepare, timestamp


def connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('Install the PostgreSQL extra: pip install -e ".[postgres]"') from exc
    database_url = os.environ["DATABASE_URL"]
    try:
        return psycopg.connect(database_url, options="-c timezone=UTC")
    except psycopg.Error:
        raise RuntimeError("PostgreSQL connection failed; check DATABASE_URL and server availability.") from None


def initialize():
    sql_dir = Path(__file__).resolve().parents[2] / "sql"
    with connect() as connection:
        for name in ("001_schema.sql", "002_metrics.sql"):
            connection.execute((sql_dir / name).read_text(encoding="utf-8"))


def snapshot(connection):
    state = empty_state()
    for entity, fields in FIELDS.items():
        # Names originate only in the constant contract, never in external input.
        for values in connection.execute(f"SELECT {','.join(fields)} FROM staging.{entity}"):
            row = {field: str(value) for field, value in zip(fields, values)}
            state[entity][identity(entity, row)] = row
    return state


def load(batch, as_of):
    """Persist raw lineage, then atomically validate/upsert the canonical batch."""
    from psycopg.types.json import Jsonb

    run_id = uuid4()
    received = sum(len(rows) for rows in batch.values())
    timestamp(as_of)
    with connect() as connection:
        connection.execute(
            "INSERT INTO raw.pipeline_runs(run_id,status,as_of,records_received) VALUES (%s,'running',%s,%s)",
            (run_id, as_of, received))
        for entity, rows in batch.items():
            for number, row in enumerate(rows, 2):
                connection.execute("INSERT INTO raw.records(run_id,row_number,entity,payload) VALUES (%s,%s,%s,%s)",
                                   (run_id, number, entity, Jsonb(row)))
    try:
        with connect() as connection:
            # Serialize loaders, including a complete prospective-history validation.
            connection.execute("SELECT pg_advisory_xact_lock(742159031)")
            existing = snapshot(connection)
            candidate, rejected, counts = prepare(batch, existing, as_of)
            for item in rejected:
                connection.execute(
                    "INSERT INTO raw.rejected_records(run_id,row_number,entity,payload,reason) VALUES (%s,%s,%s,%s,%s)",
                    (run_id, item["row_number"], item["entity"], Jsonb(item["payload"]), item["reason"]))
            if not rejected:
                for entity, fields in FIELDS.items():
                    keys = KEYS[entity]
                    changes = [field for field in fields if field not in keys]
                    sql = (f"INSERT INTO staging.{entity} ({','.join(fields)}) "
                           f"VALUES ({','.join(['%s'] * len(fields))}) "
                           f"ON CONFLICT ({','.join(keys)}) DO UPDATE SET "
                           + ','.join(f"{field}=EXCLUDED.{field}" for field in changes))
                    for row in batch[entity]:
                        if not equivalent(entity, existing[entity].get(identity(entity, row)), row):
                            connection.execute(sql, tuple(row[field] for field in fields))
            status = "failed" if rejected else "succeeded"
            connection.execute(
                "UPDATE raw.pipeline_runs SET finished_at=clock_timestamp(),status=%s,records_accepted=%s,"
                "records_rejected=%s,records_inserted=%s,records_updated=%s,records_unchanged=%s,error=%s WHERE run_id=%s",
                (status, counts["accepted"], counts["rejected"], counts["inserted"], counts["updated"],
                 counts["unchanged"], "Batch validation failed; no canonical changes" if rejected else None, run_id))
        return {"run_id": str(run_id), "status": status, **counts, "rejections": rejected}
    except Exception as exc:
        # Do not log connection details or arbitrary driver errors containing credentials/data.
        with connect() as connection:
            connection.execute(
                "UPDATE raw.pipeline_runs SET finished_at=clock_timestamp(),status='failed',error=%s WHERE run_id=%s",
                (f"Database load failed ({type(exc).__name__}); canonical transaction rolled back", run_id))
        raise RuntimeError(f"Database load failed; inspect run {run_id}. Canonical transaction rolled back.") from None


def query_metrics(as_of):
    timestamp(as_of)
    with connect() as connection:
        cursor = connection.execute("SELECT * FROM analytics.ticket_metrics(%s) ORDER BY source_system,ticket_id", (as_of,))
        fields = [column.name for column in cursor.description]
        return [dict(zip(fields, row)) for row in cursor]
