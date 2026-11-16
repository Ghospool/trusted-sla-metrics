import copy
import os
from decimal import Decimal
import unittest
from unittest.mock import patch

from sla_pipeline import postgres
from sla_pipeline.model import read_batch
from support import AS_OF, HEADERS, SAMPLE, expected_rows, normalized_metrics


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL") and os.environ.get("SLA_TEST_ALLOW_RESET") == "1",
                     "Requires dedicated TEST_DATABASE_URL and explicit SLA_TEST_ALLOW_RESET=1 acknowledgment")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import psycopg
        except ImportError:
            raise unittest.SkipTest("Optional psycopg driver unavailable")
        url = os.environ["TEST_DATABASE_URL"]
        if url == os.environ.get("DATABASE_URL"):
            raise unittest.SkipTest("TEST_DATABASE_URL must not target the configured application DATABASE_URL")
        try:
            connection = psycopg.connect(url, connect_timeout=5)
        except psycopg.OperationalError:
            raise unittest.SkipTest("Dedicated test PostgreSQL database is unavailable (connection details omitted)")
        with connection:
            occupied = connection.execute(
                "SELECT n.nspname FROM pg_namespace n WHERE n.nspname IN ('raw','staging','analytics') "
                "AND (EXISTS (SELECT 1 FROM pg_class c WHERE c.relnamespace=n.oid) "
                "OR EXISTS (SELECT 1 FROM pg_proc p WHERE p.pronamespace=n.oid) "
                "OR EXISTS (SELECT 1 FROM pg_type t WHERE t.typnamespace=n.oid))"
            ).fetchall()
        if occupied:
            raise unittest.SkipTest("Test requires empty raw/staging/analytics schemas; never drops existing evidence")
        cls.environment = patch.dict(os.environ, {"DATABASE_URL": url})
        cls.environment.start()
        cls.addClassCleanup(cls.environment.stop)
        postgres.initialize()

    def canonical_snapshot(self):
        with postgres.connect() as connection:
            return {entity: connection.execute(
                f"SELECT to_jsonb(t) FROM staging.{entity} t ORDER BY to_jsonb(t)::text"
            ).fetchall() for entity in HEADERS}

    def assert_metrics(self, expected):
        self.assertEqual(normalized_metrics(expected_rows(expected)),
                         normalized_metrics(postgres.query_metrics(AS_OF)))

    def assert_audit(self, result):
        with postgres.connect() as connection:
            row = connection.execute(
                "SELECT status,records_received,records_accepted,records_rejected,records_inserted,"
                "records_updated,records_unchanged,finished_at IS NOT NULL,error "
                "FROM raw.pipeline_runs WHERE run_id=%s", (result["run_id"],)
            ).fetchone()
            self.assertEqual(tuple(result[field] for field in (
                "status", "received", "accepted", "rejected", "inserted", "updated", "unchanged")), row[:7])
            self.assertTrue(row[7])
            self.assertEqual(result["status"] == "failed", row[8] is not None)
            raw_count = connection.execute("SELECT count(*) FROM raw.records WHERE run_id=%s",
                                           (result["run_id"],)).fetchone()[0]
            rejected_count = connection.execute("SELECT count(*) FROM raw.rejected_records WHERE run_id=%s",
                                                (result["run_id"],)).fetchone()[0]
            self.assertEqual(result["received"], raw_count)
            self.assertEqual(result["rejected"], rejected_count)

    def test_disposable_database_public_load_and_metrics_sequence(self):
        batch = read_batch(SAMPLE)
        loaded = postgres.load(batch, AS_OF)
        self.assertEqual("succeeded", loaded["status"])
        self.assertEqual(loaded["received"], loaded["inserted"])
        self.assert_audit(loaded)
        self.assert_metrics("sample_metrics.csv")
        initial = self.canonical_snapshot()

        invalid = read_batch(SAMPLE / "invalid_batch")
        invalid["teams"][0]["team_name"] = "Must not survive failed batch"
        failed = postgres.load(invalid, AS_OF)
        self.assertEqual("failed", failed["status"])
        self.assertGreater(failed["rejected"], 0)
        self.assertEqual((0, 0, 0), (failed["inserted"], failed["updated"], failed["unchanged"]))
        self.assert_audit(failed)
        self.assertEqual(initial, self.canonical_snapshot())
        self.assert_metrics("sample_metrics.csv")

        replay = postgres.load(batch, AS_OF)
        self.assertEqual(replay["received"], replay["unchanged"])
        self.assertEqual((0, 0), (replay["inserted"], replay["updated"]))
        self.assert_audit(replay)
        self.assertEqual(initial, self.canonical_snapshot())

        from psycopg.conninfo import make_conninfo
        non_utc_url = make_conninfo(os.environ["DATABASE_URL"], options="-c timezone=America/New_York")
        with patch.dict(os.environ, {"DATABASE_URL": non_utc_url}):
            with postgres.connect() as connection:
                self.assertEqual("UTC", connection.execute("SHOW timezone").fetchone()[0])
            timezone_replay = postgres.load(batch, AS_OF)
            self.assertEqual("succeeded", timezone_replay["status"])
            self.assertEqual(timezone_replay["received"], timezone_replay["unchanged"])
            self.assert_audit(timezone_replay)
            self.assertEqual(initial, self.canonical_snapshot())
            self.assert_metrics("sample_metrics.csv")

        historical = normalized_metrics(postgres.query_metrics("2025-01-07T19:30:00Z"))
        self.assertNotIn(("atlas_service", "T001"), historical)
        row = historical[("atlas_service", "T002")]
        self.assertEqual(("waiting", 240, 450, 1, False),
                         (row["current_status"], row["resolution_minutes"], row["backlog_age_minutes"],
                          row["reopened_count"], row["resolution_breached"]))
        self.assertEqual([], postgres.query_metrics("2025-01-01T00:00:00Z"))

        late = read_batch(SAMPLE / "late_event_batch")
        late_result = postgres.load(late, AS_OF)
        self.assertEqual("succeeded", late_result["status"])
        self.assertEqual(2, late_result["inserted"])
        self.assert_audit(late_result)
        self.assert_metrics("after_late_arrival_metrics.csv")
        late_history = normalized_metrics(postgres.query_metrics("2025-01-07T00:30:00Z"))
        row = late_history[("beacon_desk", "T004")]
        self.assertEqual(("waiting", 20, 10, 30),
                         (row["current_status"], row["resolution_minutes"],
                          row["first_response_minutes"], row["backlog_age_minutes"]))
        before_replay = self.canonical_snapshot()
        late_replay = postgres.load(late, AS_OF)
        self.assertEqual(late_replay["received"], late_replay["unchanged"])
        self.assert_audit(late_replay)
        self.assertEqual(before_replay, self.canonical_snapshot())

        corrected = read_batch(SAMPLE / "corrected_batch")
        correction_result = postgres.load(corrected, AS_OF)
        self.assertEqual("succeeded", correction_result["status"])
        self.assertEqual(3, correction_result["inserted"])
        self.assertEqual(correction_result["received"] - 3, correction_result["unchanged"])
        self.assert_audit(correction_result)
        combined = expected_rows("after_late_arrival_metrics.csv") + expected_rows("corrected_batch_metrics.csv")
        self.assertEqual(normalized_metrics(combined), normalized_metrics(postgres.query_metrics(AS_OF)))
        correction_replay = postgres.load(corrected, AS_OF)
        self.assertEqual(correction_replay["received"], correction_replay["unchanged"])
        self.assert_audit(correction_replay)

        update = {entity: [] for entity in HEADERS}
        update["events"] = [copy.deepcopy(batch["events"][0])]
        update["events"][0]["occurred_at"] = "2025-01-07T22:16:00Z"
        updated = postgres.load(update, AS_OF)
        self.assertEqual((0, 1, 0), (updated["inserted"], updated["updated"], updated["unchanged"]))
        self.assert_audit(updated)
        updated_metrics = normalized_metrics(postgres.query_metrics(AS_OF))[("atlas_service", "T001")]
        self.assertEqual(16, updated_metrics["first_response_minutes"])
        self.assertTrue(updated_metrics["response_breached"])
        update_replay = postgres.load(update, AS_OF)
        self.assertEqual(1, update_replay["unchanged"])
        self.assert_audit(update_replay)

        before_move = self.canonical_snapshot()
        update["events"][0]["ticket_id"] = "T004"
        moved = postgres.load(update, AS_OF)
        self.assertEqual("failed", moved["status"])
        self.assertTrue(any("cannot be moved" in item["reason"] for item in moved["rejections"]))
        self.assert_audit(moved)
        self.assertEqual(before_move, self.canonical_snapshot())

        fractional = {entity: [] for entity in HEADERS}
        policy = copy.deepcopy(batch["policies"][0])
        policy["response_target_minutes"] = "0.005"
        policy["resolution_target_minutes"] = "0.005"
        fractional["policies"] = [policy]
        ticket = copy.deepcopy(batch["tickets"][0])
        ticket.update(ticket_id="FRACTIONAL", created_at="2025-01-07T00:00:00Z")
        fractional["tickets"] = [ticket]
        fractional["events"] = [
            {"source_system": "atlas_service", "event_id": "FRAC01", "ticket_id": "FRACTIONAL",
             "occurred_at": "2025-01-07T00:00:00.100000Z", "event_type": "responded"},
            {"source_system": "atlas_service", "event_id": "FRAC02", "ticket_id": "FRACTIONAL",
             "occurred_at": "2025-01-07T00:00:00.300000Z", "event_type": "resolved"},
        ]
        fractional_result = postgres.load(fractional, AS_OF)
        self.assertEqual("succeeded", fractional_result["status"])
        self.assert_audit(fractional_result)
        row = normalized_metrics(postgres.query_metrics(AS_OF))[("atlas_service", "FRACTIONAL")]
        self.assertEqual(Decimal("0.005"), row["resolution_minutes"])
        self.assertFalse(row["resolution_breached"])
        fractional["events"][1]["occurred_at"] = "2025-01-07T00:00:00.300001Z"
        over_result = postgres.load(fractional, AS_OF)
        self.assertEqual("succeeded", over_result["status"])
        self.assert_audit(over_result)
        row = normalized_metrics(postgres.query_metrics(AS_OF))[("atlas_service", "FRACTIONAL")]
        self.assertTrue(row["resolution_breached"])


if __name__ == "__main__":
    unittest.main()
