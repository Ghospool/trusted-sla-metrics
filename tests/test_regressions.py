import copy
import csv
import unittest
from decimal import Decimal

from sla_pipeline.model import empty_state, metrics, prepare, read_batch
from support import AS_OF, SAMPLE, ROOT, event


class RegressionTests(unittest.TestCase):
    def fractional_batch(self):
        batch = read_batch(SAMPLE)
        ticket = copy.deepcopy(batch["tickets"][0])
        ticket["created_at"] = "2025-01-07T00:00:00Z"
        batch["tickets"] = [ticket]
        batch["events"] = [
            event("E01", "responded", "2025-01-07T00:00:00.100000Z"),
            event("E02", "resolved", "2025-01-07T00:00:00.300000Z"),
        ]
        batch["policies"][0]["response_target_minutes"] = "0.005"
        batch["policies"][0]["resolution_target_minutes"] = "0.005"
        return batch

    def loaded_metrics(self, batch, cutoff=AS_OF):
        state, rejected, _ = prepare(batch, empty_state(), AS_OF)
        self.assertEqual([], rejected)
        return metrics(state, cutoff)[0]

    def test_fractional_segments_do_not_create_false_resolution_breach(self):
        row = self.loaded_metrics(self.fractional_batch())
        self.assertEqual(Decimal("0.005"), row["resolution_minutes"])
        self.assertFalse(row["resolution_breached"])

    def test_first_response_fractional_equality_is_not_a_breach(self):
        batch = self.fractional_batch()
        batch["events"][0]["occurred_at"] = "2025-01-07T00:00:00.300000Z"
        row = self.loaded_metrics(batch)
        self.assertEqual(Decimal("0.005"), row["first_response_minutes"])
        self.assertFalse(row["response_breached"])
        self.assertFalse(row["resolution_breached"])

    def test_fractional_pause_intervals_preserve_exact_active_time(self):
        batch = self.fractional_batch()
        batch["events"] = [
            event("E01", "responded", "2025-01-07T00:00:00.100000Z"),
            event("E02", "waiting", "2025-01-07T00:00:00.200000Z"),
            event("E03", "resumed", "2025-01-07T00:00:00.400000Z"),
            event("E04", "resolved", "2025-01-07T00:00:00.500000Z"),
        ]
        row = self.loaded_metrics(batch)
        self.assertEqual(Decimal("0.005"), row["resolution_minutes"])
        self.assertFalse(row["resolution_breached"])

    def test_unanswered_fractional_equality_then_one_microsecond_over(self):
        batch = self.fractional_batch()
        batch["events"] = []
        equal = self.loaded_metrics(batch, "2025-01-07T00:00:00.300000Z")
        self.assertEqual(Decimal("0.005"), equal["backlog_age_minutes"])
        self.assertFalse(equal["response_breached"])
        self.assertFalse(equal["resolution_breached"])
        over = self.loaded_metrics(batch, "2025-01-07T00:00:00.300001Z")
        self.assertTrue(over["response_breached"])
        self.assertTrue(over["resolution_breached"])

    def test_staffing_postgresql_integer_boundary(self):
        batch = read_batch(SAMPLE)
        batch["teams"][0]["staffing_count"] = "2147483647"
        _, rejected, _ = prepare(batch, empty_state(), AS_OF)
        self.assertEqual([], rejected)
        batch["teams"][0]["staffing_count"] = "2147483648"
        state, rejected, counts = prepare(batch, empty_state(), AS_OF)
        self.assertEqual(empty_state(), state)
        self.assertTrue(any("integer maximum" in item["reason"] for item in rejected))
        self.assertEqual(0, counts["inserted"])

    def test_entity_mapping_order_is_not_a_foreign_key_dependency(self):
        batch = read_batch(SAMPLE)
        reverse = dict(reversed(list(batch.items())))
        state, rejected, counts = prepare(reverse, empty_state(), AS_OF)
        self.assertEqual([], rejected)
        self.assertEqual(9, len(metrics(state, AS_OF)))
        self.assertEqual(counts["received"], counts["inserted"])

    def test_missing_entity_is_an_explicit_batch_error(self):
        batch = read_batch(SAMPLE)
        del batch["policies"]
        with self.assertRaisesRegex(ValueError, "batch must contain exactly"):
            prepare(batch, empty_state(), AS_OF)

    def test_committed_rejection_example_matches_observed_rejections(self):
        _, rejected, _ = prepare(read_batch(SAMPLE / "invalid_batch"), empty_state(), AS_OF)
        with (ROOT / "data/expected/invalid_batch_rejections.csv").open(newline="", encoding="utf-8") as stream:
            expected = list(csv.DictReader(stream))
        actual = [{"entity": row["entity"], "row_number": str(row["row_number"]), "reason": row["reason"]}
                  for row in rejected]
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
