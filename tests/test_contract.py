import copy
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sla_pipeline.generate import generate
from sla_pipeline.model import empty_state, metrics, prepare, read_batch
from support import AS_OF, HEADERS, ROOT, SAMPLE, event, expected_rows, normalized_metrics, write_batch


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.batch = read_batch(SAMPLE)

    def load(self, batch=None, existing=None, as_of=AS_OF):
        state, rejected, counts = prepare(self.batch if batch is None else batch,
                                          empty_state() if existing is None else existing, as_of)
        self.assertEqual([], rejected)
        self.assertEqual(0, counts["rejected"])
        return state, counts

    def assert_rejected(self, batch, reason, existing=None):
        existing = empty_state() if existing is None else existing
        before = copy.deepcopy(existing)
        state, rejected, counts = prepare(batch, existing, AS_OF)
        self.assertTrue(rejected)
        self.assertTrue(any(reason in item["reason"] for item in rejected), rejected)
        self.assertEqual(before, state)
        self.assertEqual(before, existing)
        self.assertEqual(counts["received"], counts["accepted"] + counts["rejected"])
        for field in ("inserted", "updated", "unchanged"):
            self.assertEqual(0, counts[field])
        return rejected, counts

    def test_sample_matches_hand_expected_csv(self):
        state, counts = self.load()
        self.assertEqual(normalized_metrics(expected_rows("sample_metrics.csv")),
                         normalized_metrics(metrics(state, AS_OF)))
        received = sum(map(len, self.batch.values()))
        self.assertEqual({"received": received, "accepted": received, "rejected": 0,
                          "inserted": received, "updated": 0, "unchanged": 0}, counts)

    def test_csv_headers_must_be_exact_and_ordered(self):
        for entity, fields in HEADERS.items():
            variants = [fields[::-1], fields[:-1], (*fields, "extra"),
                        (f" {fields[0]}", *fields[1:]), (fields[0], *fields)]
            for headers in variants:
                with self.subTest(entity=entity, headers=headers), tempfile.TemporaryDirectory() as directory:
                    write_batch(directory, self.batch)
                    Path(directory, f"{entity}.csv").write_text(
                        ",".join(headers) + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "expected ordered headers"):
                        read_batch(directory)

    def test_missing_extra_blank_and_whitespace_fields_reject(self):
        for entity in HEADERS:
            field = HEADERS[entity][0]
            for kind in ("missing", "extra", "blank", "space", "trailing", "null"):
                with self.subTest(entity=entity, kind=kind):
                    batch = copy.deepcopy(self.batch)
                    row = batch[entity][0]
                    if kind == "missing":
                        del row[field]
                    elif kind == "extra":
                        row["unexpected"] = "value"
                    elif kind == "null":
                        row[field] = None
                    else:
                        row[field] = {"blank": "", "space": " ", "trailing": row[field] + " "}[kind]
                    self.assert_rejected(batch, "field" if kind != "trailing" else "whitespace")

    def test_csv_missing_or_extra_cells_reject(self):
        for suffix in ("\nnew-team,New Team\n", "\nnew-team,New Team,3,extra\n"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                write_batch(directory, self.batch)
                with Path(directory, "teams.csv").open("a", encoding="utf-8") as stream:
                    stream.write(suffix.lstrip("\n"))
                self.assert_rejected(read_batch(directory), "field")

    def test_non_utc_naive_invalid_and_future_timestamps_reject(self):
        for entity, field in (("tickets", "created_at"), ("events", "occurred_at")):
            for value in ("2025-01-07T22:00:00+01:00", "2025-01-07T22:00:00",
                          "not-a-timestamp", "2025-01-09T00:00:00Z"):
                with self.subTest(entity=entity, value=value):
                    batch = copy.deepcopy(self.batch)
                    batch[entity][0][field] = value
                    self.assert_rejected(batch, "after run as_of" if "01-09" in value else "")

    def test_numeric_policy_targets_and_staffing_validation(self):
        for field in ("response_target_minutes", "resolution_target_minutes"):
            for value in ("NaN", "Infinity", "-Infinity", "0", "-1", "not-a-number"):
                with self.subTest(field=field, value=value):
                    batch = copy.deepcopy(self.batch)
                    batch["policies"][0][field] = value
                    self.assert_rejected(batch, "")
        for value in ("-1", "1.5", "NaN", "２", "+1"):
            with self.subTest(staffing=value):
                batch = copy.deepcopy(self.batch)
                batch["teams"][0]["staffing_count"] = value
                self.assert_rejected(batch, "nonnegative integer")
        batch = copy.deepcopy(self.batch)
        batch["teams"][0]["staffing_count"] = "0"
        self.load(batch)

    def test_unknown_foreign_keys_types_and_duplicate_rows_reject(self):
        cases = [("tickets", "team_id", "missing", "unknown team"),
                 ("tickets", "priority", "P9", "unknown priority"),
                 ("events", "ticket_id", "missing", "unknown ticket"),
                 ("events", "source_system", "missing", "unknown ticket"),
                 ("events", "event_type", "closed", "unknown event_type"),
                 ("policies", "priority", "P9", "priority must be")]
        for entity, field, value, reason in cases:
            with self.subTest(entity=entity, field=field):
                batch = copy.deepcopy(self.batch)
                batch[entity][0][field] = value
                self.assert_rejected(batch, reason)
        for entity in HEADERS:
            with self.subTest(duplicate=entity):
                batch = copy.deepcopy(self.batch)
                batch[entity].append(copy.deepcopy(batch[entity][0]))
                self.assert_rejected(batch, "duplicate identity")

    def test_failed_batch_does_not_apply_other_valid_changes(self):
        state, _ = self.load()
        batch = copy.deepcopy(self.batch)
        batch["teams"][0]["team_name"] = "Changed but must roll back"
        batch["tickets"][0]["priority"] = "P9"
        batch["events"].append(event("new-response", "responded", "2025-01-07T23:35:00Z", "T004"))
        self.assert_rejected(batch, "unknown priority", state)

    def test_invalid_corrected_idempotent_replay_counts(self):
        invalid = read_batch(SAMPLE / "invalid_batch")
        _, bad_counts = self.assert_rejected(invalid, "unknown priority")
        self.assertGreater(bad_counts["rejected"], 0)
        corrected = read_batch(SAMPLE / "corrected_batch")
        state, inserted = self.load(corrected)
        received = sum(map(len, corrected.values()))
        self.assertEqual(received, inserted["inserted"])
        self.assertEqual(normalized_metrics(expected_rows("corrected_batch_metrics.csv")),
                         normalized_metrics(metrics(state, AS_OF)))
        replayed, replay = self.load(corrected, state)
        self.assertEqual(state, replayed)
        self.assertEqual(received, replay["unchanged"])
        self.assertEqual(0, replay["inserted"])
        self.assertEqual(0, replay["updated"])

    def test_corrections_report_updated_and_change_metrics(self):
        state, _ = self.load()
        correction = {entity: [] for entity in HEADERS}
        row = copy.deepcopy(self.batch["events"][0])
        row["occurred_at"] = "2025-01-07T22:16:00Z"
        correction["events"] = [row]
        updated, counts = self.load(correction, state)
        self.assertEqual({"received": 1, "accepted": 1, "rejected": 0,
                          "inserted": 0, "updated": 1, "unchanged": 0}, counts)
        result = normalized_metrics(metrics(updated, AS_OF))[("atlas_service", "T001")]
        self.assertEqual(16, result["first_response_minutes"])
        self.assertTrue(result["response_breached"])
        self.assertEqual(15, normalized_metrics(metrics(state, AS_OF))[("atlas_service", "T001")]["first_response_minutes"])
        _, replay = self.load(correction, updated)
        self.assertEqual(1, replay["unchanged"])

    def test_equivalent_utc_and_numeric_formatting_is_unchanged(self):
        state, _ = self.load()
        batch = copy.deepcopy(self.batch)
        for row in batch["policies"]:
            row["response_target_minutes"] += ".0"
            row["resolution_target_minutes"] += ".00"
        for row in batch["teams"]:
            row["staffing_count"] = "0" + row["staffing_count"]
        for entity, field in (("tickets", "created_at"), ("events", "occurred_at")):
            for row in batch[entity]:
                row[field] = row[field].replace("Z", "+00:00")
        _, counts = self.load(batch, state)
        self.assertEqual(counts["received"], counts["unchanged"])
        self.assertEqual(0, counts["updated"])

    def test_existing_event_cannot_move_between_tickets(self):
        state, _ = self.load()
        batch = {entity: [] for entity in HEADERS}
        row = copy.deepcopy(self.batch["events"][0])
        row["ticket_id"] = "T004"
        batch["events"] = [row]
        self.assert_rejected(batch, "cannot be moved", state)

    def test_late_events_recompute_history_and_are_idempotent(self):
        state, _ = self.load()
        late = read_batch(SAMPLE / "late_event_batch")
        updated, counts = self.load(late, state)
        self.assertEqual(2, counts["inserted"])
        self.assertEqual(normalized_metrics(expected_rows("after_late_arrival_metrics.csv")),
                         normalized_metrics(metrics(updated, AS_OF)))
        self.assertEqual(60, normalized_metrics(metrics(state, AS_OF))[("beacon_desk", "T004")]["resolution_minutes"])
        _, replay = self.load(late, updated)
        self.assertEqual(replay["received"], replay["unchanged"])

    def test_same_ticket_and_event_ids_remain_source_scoped(self):
        batch = copy.deepcopy(self.batch)
        beacon = next(row for row in batch["events"] if row["source_system"] == "beacon_desk")
        beacon["event_id"] = batch["events"][0]["event_id"]
        state, _ = self.load(batch)
        result = normalized_metrics(metrics(state, AS_OF))
        self.assertEqual(9, len(result))
        self.assertEqual(15, result[("atlas_service", "T001")]["first_response_minutes"])
        self.assertEqual(30, result[("beacon_desk", "T001")]["first_response_minutes"])

    def test_pause_resume_reopen_cumulative_time_and_backlog(self):
        state, _ = self.load()
        result = normalized_metrics(metrics(state, AS_OF))
        for key, status, active, age, reopens in (
            (("atlas_service", "T002"), "resolved", 300, None, 1),
            (("atlas_service", "T003"), "waiting", 60, 240, 0),
            (("beacon_desk", "T002"), "open", 180, 2880, 1),
            (("beacon_desk", "T003"), "waiting", 60, 840, 0),
        ):
            with self.subTest(ticket=key):
                row = result[key]
                self.assertEqual((status, active, age, reopens),
                                 (row["current_status"], row["resolution_minutes"],
                                  row["backlog_age_minutes"], row["reopened_count"]))
        self.assertTrue(result[("atlas_service", "T002")]["resolution_breached"])
        self.assertTrue(result[("beacon_desk", "T003")]["response_breached"])

    def test_first_response_strict_threshold_and_unanswered_equality(self):
        state, _ = self.load()
        final = normalized_metrics(metrics(state, AS_OF))
        equal = final[("atlas_service", "T001")]
        self.assertEqual(15, equal["first_response_minutes"])
        self.assertEqual(60, equal["resolution_minutes"])
        self.assertFalse(equal["response_breached"])
        self.assertFalse(equal["resolution_breached"])
        repeated = final[("atlas_service", "T005")]
        self.assertEqual(0, repeated["first_response_minutes"])
        self.assertEqual(20, repeated["resolution_minutes"])
        at_limit = normalized_metrics(metrics(state, "2025-01-07T23:45:00Z"))[("atlas_service", "T004")]
        self.assertIsNone(at_limit["first_response_minutes"])
        self.assertEqual(15, at_limit["backlog_age_minutes"])
        self.assertFalse(at_limit["response_breached"])
        over_limit = normalized_metrics(metrics(state, "2025-01-07T23:45:01Z"))[("atlas_service", "T004")]
        self.assertTrue(over_limit["response_breached"])

    def test_historical_cutoff_excludes_future_tickets_and_events(self):
        state, _ = self.load()
        result = normalized_metrics(metrics(state, "2025-01-07T19:30:00Z"))
        self.assertNotIn(("atlas_service", "T001"), result)
        row = result[("atlas_service", "T002")]
        self.assertEqual(("waiting", 240, 450, 1),
                         (row["current_status"], row["resolution_minutes"], row["backlog_age_minutes"], row["reopened_count"]))
        self.assertFalse(row["resolution_breached"])
        self.assertEqual([], metrics(state, "2025-01-01T00:00:00Z"))
        at_creation = normalized_metrics(metrics(state, "2025-01-07T23:30:00Z"))[("atlas_service", "T004")]
        self.assertEqual(0, at_creation["resolution_minutes"])

    def test_equal_timestamp_event_ids_use_lexical_not_input_order(self):
        batch = copy.deepcopy(self.batch)
        batch["events"].reverse()
        state, _ = self.load(batch)
        self.assertEqual(normalized_metrics(expected_rows("sample_metrics.csv")),
                         normalized_metrics(metrics(state, AS_OF)))
        batch = copy.deepcopy(self.batch)
        batch["events"] = [row for row in batch["events"] if row["ticket_id"] != "T005"]
        batch["events"].extend([
            event("z-resolve", "resolved", "2025-01-07T23:20:00Z", "T005"),
            event("a-wait", "waiting", "2025-01-07T23:20:00Z", "T005"),
            event("b-resume", "resumed", "2025-01-07T23:20:00Z", "T005"),
        ])
        state, _ = self.load(batch)
        row = normalized_metrics(metrics(state, AS_OF))[("atlas_service", "T005")]
        self.assertEqual(("resolved", 20), (row["current_status"], row["resolution_minutes"]))

    def test_invalid_lifecycle_and_before_creation_reject(self):
        cases = [("resumed", "2025-01-07T22:05:00Z", "requires waiting"),
                 ("reopened", "2025-01-07T22:05:00Z", "requires resolved"),
                 ("waiting", "2025-01-07T23:05:00Z", "requires open"),
                 ("responded", "2025-01-07T23:05:00Z", "requires open"),
                 ("responded", "2025-01-07T21:59:00Z", "precedes ticket creation")]
        for kind, moment, reason in cases:
            with self.subTest(kind=kind, moment=moment):
                batch = copy.deepcopy(self.batch)
                batch["events"].append(event("invalid", kind, moment))
                self.assert_rejected(batch, reason)

    def test_ticket_correction_cannot_invalidate_existing_history(self):
        state, _ = self.load()
        batch = {entity: [] for entity in HEADERS}
        ticket = copy.deepcopy(self.batch["tickets"][0])
        ticket["created_at"] = "2025-01-07T22:16:00Z"
        batch["tickets"] = [ticket]
        self.assert_rejected(batch, "precedes ticket creation", state)


class GeneratorTests(unittest.TestCase):
    def test_seed_is_byte_reproducible_and_changes_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, seed in (("first", 42), ("second", 42), ("different", 43)):
                generate(base / name, seed=seed, tickets=100)
            for entity, headers in HEADERS.items():
                with self.subTest(entity=entity):
                    first = (base / "first" / f"{entity}.csv").read_bytes()
                    self.assertEqual(first, (base / "second" / f"{entity}.csv").read_bytes())
                    self.assertEqual(",".join(headers), first.decode().splitlines()[0])
            self.assertNotEqual((base / "first" / "tickets.csv").read_bytes(),
                                (base / "different" / "tickets.csv").read_bytes())

    def test_generated_rows_validate_across_seeds_and_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            for seed, size in ((0, 0), (1, 1), (42, 100), (99, 301)):
                with self.subTest(seed=seed, size=size):
                    generate(Path(directory), seed=seed, tickets=size)
                    batch = read_batch(directory)
                    state, rejected, counts = prepare(batch, empty_state(), AS_OF)
                    self.assertEqual([], rejected)
                    self.assertEqual(size, len(batch["tickets"]))
                    self.assertEqual(size, len(metrics(state, AS_OF)))
                    self.assertEqual(counts["received"], counts["inserted"])
                    self.assertEqual(size, len({(row["source_system"], row["ticket_id"]) for row in batch["tickets"]}))
                    if size >= 2:
                        self.assertLess(len({row["ticket_id"] for row in batch["tickets"]}), size)

    def test_rejects_invalid_counts_and_preserves_unrelated_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for value in (-1, True, 1.5, "10"):
                with self.subTest(tickets=value), self.assertRaises(ValueError):
                    generate(path, tickets=value)
            marker = path / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            generate(path, tickets=2)
            generate(path, tickets=0)
            self.assertEqual("keep", marker.read_text(encoding="utf-8"))
            self.assertEqual([], read_batch(path)["tickets"])
            self.assertEqual([], read_batch(path)["events"])


class CliTests(unittest.TestCase):
    def cli(self, *arguments):
        executable = shutil.which("py") if os.name == "nt" else sys.executable
        if executable is None:
            self.skipTest("Python launcher unavailable for subprocess CLI checks")
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        try:
            return subprocess.run([executable, "-m", "sla_pipeline", *map(str, arguments)],
                                  cwd=ROOT, env=env, text=True, capture_output=True,
                                  timeout=30, check=False)
        except PermissionError as exc:
            self.skipTest(f"Application policy blocks CLI subprocess: {exc}")

    def test_validate_success_and_failure_exit_codes(self):
        valid = self.cli("validate", "--input", SAMPLE)
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual(0, json.loads(valid.stdout)["rejected"])
        invalid = self.cli("validate", "--input", SAMPLE / "invalid_batch")
        self.assertEqual(1, invalid.returncode, invalid.stderr)
        self.assertGreater(json.loads(invalid.stdout)["rejected"], 0)
        with tempfile.TemporaryDirectory() as directory:
            write_batch(directory, read_batch(SAMPLE))
            Path(directory, "teams.csv").write_text("wrong,headers\n", encoding="utf-8")
            malformed = self.cli("validate", "--input", directory)
            self.assertEqual(1, malformed.returncode)
            self.assertIn("expected ordered headers", malformed.stderr)
        missing = self.cli("validate", "--input", SAMPLE / "does-not-exist")
        self.assertEqual(1, missing.returncode)
        syntax = self.cli("validate")
        self.assertEqual(2, syntax.returncode)

    def test_demo_writes_failed_corrected_replay_log_and_expected_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            completed = self.cli("demo", "--input", SAMPLE, "--output", output)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("not PostgreSQL or KNIME", json.loads(completed.stdout)["mode"])
            logs = json.loads((output / "run_log.json").read_text(encoding="utf-8"))
            self.assertEqual(["failed", "succeeded", "succeeded"], [row["status"] for row in logs])
            self.assertEqual(0, logs[0]["inserted"])
            self.assertGreater(logs[0]["rejected"], 0)
            self.assertEqual(logs[1]["received"], logs[1]["inserted"])
            self.assertEqual(logs[2]["received"], logs[2]["unchanged"])
            self.assertEqual((0, 0), (logs[2]["inserted"], logs[2]["updated"]))
            with (output / "ticket_metrics.csv").open(newline="", encoding="utf-8") as stream:
                self.assertEqual(normalized_metrics(expected_rows("sample_metrics.csv")),
                                 normalized_metrics(list(csv.DictReader(stream))))

    def test_generate_cli_outputs_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = self.cli("generate", "--output", directory, "--seed", 7, "--tickets", 12)
            self.assertEqual(0, generated.returncode, generated.stderr)
            validated = self.cli("validate", "--input", directory)
            self.assertEqual(0, validated.returncode, validated.stderr)
            self.assertEqual(12, len(read_batch(directory)["tickets"]))
            invalid = self.cli("generate", "--output", directory, "--tickets", -1)
            self.assertEqual(1, invalid.returncode)


if __name__ == "__main__":
    unittest.main()
