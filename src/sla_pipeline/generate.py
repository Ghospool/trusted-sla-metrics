"""Generate deterministic, entirely fictional IT service CSV input batches."""

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

AS_OF = datetime(2025, 1, 8, tzinfo=timezone.utc)
SOURCES = ("atlas_service", "beacon_desk")
TEAMS = (
    ("service", "Fictional Service Desk", 8),
    ("platform", "Fictional Platform Operations", 5),
    ("workplace", "Fictional Workplace Support", 4),
)
POLICIES = (("P1", 15, 60), ("P2", 30, 240), ("P3", 60, 480), ("P4", 120, 1440))
HEADERS = {
    "teams.csv": ("team_id", "team_name", "staffing_count"),
    "policies.csv": ("priority", "response_target_minutes", "resolution_target_minutes"),
    "tickets.csv": ("source_system", "ticket_id", "created_at", "priority", "team_id", "subject"),
    "events.csv": ("source_system", "event_id", "ticket_id", "occurred_at", "event_type"),
}
SEQUENCES = (
    (),
    ("responded", "resolved"),
    ("responded", "waiting"),
    ("waiting", "resumed", "responded", "resolved"),
    ("responded", "resolved", "reopened", "waiting", "resumed", "resolved"),
    ("responded", "responded", "waiting", "resumed", "resolved", "reopened"),
)


def _timestamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADERS[path.name])
        writer.writerows(rows)


def generate(output: Path, seed: int = 42, tickets: int = 100):
    """Write four root CSVs; timestamps never exceed AS_OF.

    Repeated ticket IDs across the two sources are intentional. Reusing an
    output directory replaces only the four contract CSVs, not other files.
    """
    if isinstance(tickets, bool) or not isinstance(tickets, int) or tickets < 0:
        raise ValueError("tickets must be a nonnegative integer")
    rng = random.Random(seed)
    ticket_rows = []
    event_rows = []
    for index in range(tickets):
        source = SOURCES[index % len(SOURCES)]
        ticket_id = f"T{index // len(SOURCES) + 1:06d}"
        created_at = AS_OF - timedelta(minutes=rng.randint(720, 10080))
        priority = POLICIES[rng.randrange(len(POLICIES))][0]
        team_id = TEAMS[rng.randrange(len(TEAMS))][0]
        ticket_rows.append((
            source, ticket_id, _timestamp(created_at), priority, team_id,
            f"Fictional service request {index + 1:06d}",
        ))
        occurred_at = created_at
        sequence = SEQUENCES[index % len(SEQUENCES)]
        for step, event_type in enumerate(sequence, start=1):
            occurred_at += timedelta(minutes=rng.randint(1, 90))
            if occurred_at > AS_OF:
                break
            event_rows.append((
                source, f"E{index + 1:06d}-{step:02d}", ticket_id,
                _timestamp(occurred_at), event_type,
            ))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("teams.csv", TEAMS), ("policies.csv", POLICIES),
        ("tickets.csv", ticket_rows), ("events.csv", event_rows),
    ):
        _write_csv(output / name, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tickets", type=int, default=100)
    args = parser.parse_args()
    if args.tickets < 0:
        parser.error("--tickets must be nonnegative")
    generate(args.output, seed=args.seed, tickets=args.tickets)


if __name__ == "__main__":
    main()
