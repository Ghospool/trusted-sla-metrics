"""Shared input contract, lifecycle validation, and independent metric oracle."""

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = {
    "teams": ("team_id", "team_name", "staffing_count"),
    "policies": ("priority", "response_target_minutes", "resolution_target_minutes"),
    "tickets": ("source_system", "ticket_id", "created_at", "priority", "team_id", "subject"),
    "events": ("source_system", "event_id", "ticket_id", "occurred_at", "event_type"),
}
KEYS = {"teams": ("team_id",), "policies": ("priority",),
        "tickets": ("source_system", "ticket_id"), "events": ("source_system", "event_id")}
TRANSITIONS = {"waiting": ("open", "waiting"), "resumed": ("waiting", "open"),
               "resolved": ("open", "resolved"), "reopened": ("resolved", "open")}
AS_OF = "2025-01-08T00:00:00Z"


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must have explicit UTC offset (Z or +00:00)")
    return parsed.astimezone(timezone.utc)


def identity(entity, row):
    return tuple(row[field] for field in KEYS[entity])


def duration_minutes(delta):
    return Decimal(delta // timedelta(microseconds=1)) / Decimal(60_000_000)


def equivalent(entity, left, right):
    if left is None:
        return False
    for field in FIELDS[entity]:
        a, b = left[field], right[field]
        if field in {"created_at", "occurred_at"}:
            if timestamp(a) != timestamp(b):
                return False
        elif field in {"staffing_count", "response_target_minutes", "resolution_target_minutes"}:
            if Decimal(a) != Decimal(b):
                return False
        elif a != b:
            return False
    return True


def empty_state():
    return {entity: {} for entity in FIELDS}


def read_batch(directory):
    batch = {}
    for entity, fields in FIELDS.items():
        with (Path(directory) / f"{entity}.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(fields):
                raise ValueError(f"{entity}.csv: expected ordered headers {','.join(fields)}")
            batch[entity] = list(reader)
    return batch


def history(ticket, events):
    state = "open"
    previous = timestamp(ticket["created_at"])
    for event in sorted(events, key=lambda e: (timestamp(e["occurred_at"]), e["event_id"])):
        moment = timestamp(event["occurred_at"])
        if moment < previous:
            raise ValueError("event precedes ticket creation")
        kind = event["event_type"]
        if kind == "responded":
            if state != "open":
                raise ValueError("responded requires open state")
        else:
            required, next_state = TRANSITIONS[kind]
            if state != required:
                raise ValueError(f"{kind} requires {required} state, got {state}")
            state = next_state
        previous = moment
    return state


def prepare(batch, existing, as_of):
    """Validate a whole batch; any rejection prevents all canonical changes."""
    cutoff = timestamp(as_of)
    if set(batch) != set(FIELDS):
        raise ValueError("batch must contain exactly teams, policies, tickets, and events")
    candidate = {entity: dict(rows) for entity, rows in existing.items()}
    rejected = []
    seen = {entity: set() for entity in FIELDS}
    valid_rows = []
    for entity in FIELDS:
        for number, row in enumerate(batch[entity], 2):
            try:
                if set(row) != set(FIELDS[entity]) or any(not isinstance(v, str) or not v.strip() for v in row.values()):
                    raise ValueError("missing, extra, or blank field")
                if any(v != v.strip() for v in row.values()):
                    raise ValueError("leading/trailing whitespace is not allowed")
                key = identity(entity, row)
                if key in seen[entity]:
                    raise ValueError("duplicate identity within input batch")
                seen[entity].add(key)
                if entity == "teams" and (not row["staffing_count"].isascii() or not row["staffing_count"].isdigit()):
                    raise ValueError("staffing_count must be a nonnegative integer")
                if entity == "teams" and int(row["staffing_count"]) > 2_147_483_647:
                    raise ValueError("staffing_count exceeds PostgreSQL integer maximum 2147483647")
                if entity == "policies":
                    if row["priority"] not in {"P1", "P2", "P3", "P4"}:
                        raise ValueError("priority must be P1/P2/P3/P4")
                    for field in ("response_target_minutes", "resolution_target_minutes"):
                        value = Decimal(row[field])
                        if not value.is_finite() or value <= 0:
                            raise ValueError("SLA targets must be finite and positive")
                if entity in {"tickets", "events"}:
                    field = "created_at" if entity == "tickets" else "occurred_at"
                    if timestamp(row[field]) > cutoff:
                        raise ValueError(f"{field} is after run as_of")
                if entity == "tickets":
                    if (row["priority"],) not in candidate["policies"]:
                        raise ValueError("unknown priority")
                    if (row["team_id"],) not in candidate["teams"]:
                        raise ValueError("unknown team")
                if entity == "events":
                    old_event = existing["events"].get(key)
                    if old_event is not None and old_event["ticket_id"] != row["ticket_id"]:
                        raise ValueError("an existing event cannot be moved to another ticket")
                    if row["event_type"] not in {*TRANSITIONS, "responded"}:
                        raise ValueError("unknown event_type")
                    if (row["source_system"], row["ticket_id"]) not in candidate["tickets"]:
                        raise ValueError("unknown ticket for source_system")
                candidate[entity][key] = row
                valid_rows.append((entity, number, row))
            except (ValueError, InvalidOperation, OverflowError) as exc:
                rejected.append({"entity": entity, "row_number": number, "payload": row, "reason": str(exc)})
    events_by_ticket = {}
    for event in candidate["events"].values():
        events_by_ticket.setdefault((event["source_system"], event["ticket_id"]), []).append(event)
    invalid_tickets = {}
    for key, events in events_by_ticket.items():
        try:
            history(candidate["tickets"][key], events)
        except ValueError as exc:
            invalid_tickets[key] = str(exc)
    for entity, number, row in valid_rows:
        if entity in {"events", "tickets"} and (row["source_system"], row["ticket_id"]) in invalid_tickets:
            rejected.append({"entity": entity, "row_number": number, "payload": row,
                             "reason": invalid_tickets[(row["source_system"], row["ticket_id"])]})
    received = sum(len(rows) for rows in batch.values())
    counts = {"received": received, "accepted": received - len(rejected), "rejected": len(rejected),
              "inserted": 0, "updated": 0, "unchanged": 0}
    if rejected:
        return existing, rejected, counts
    for entity, rows in batch.items():
        for row in rows:
            old = existing[entity].get(identity(entity, row))
            counts["inserted" if old is None else "unchanged" if equivalent(entity, old, row) else "updated"] += 1
    return candidate, [], counts


def metrics(state, as_of):
    """Python oracle, not a substitute for the PostgreSQL analytics function."""
    cutoff = timestamp(as_of)
    result = []
    for key, ticket in sorted(state["tickets"].items()):
        created = timestamp(ticket["created_at"])
        if created > cutoff:
            continue
        events = sorted((e for e in state["events"].values()
                         if (e["source_system"], e["ticket_id"]) == key and timestamp(e["occurred_at"]) <= cutoff),
                        key=lambda e: (timestamp(e["occurred_at"]), e["event_id"]))
        current, previous, active, first, reopens = "open", created, timedelta(), None, 0
        for event in events:
            moment = timestamp(event["occurred_at"])
            if current == "open":
                active += moment - previous
            kind = event["event_type"]
            if kind == "responded":
                if first is None:
                    first = duration_minutes(moment - created)
            else:
                current = TRANSITIONS[kind][1]
            if kind == "reopened":
                reopens += 1
            previous = moment
        if current == "open":
            active += cutoff - previous
        policy = state["policies"][(ticket["priority"],)]
        age = duration_minutes(cutoff - created)
        active_minutes = duration_minutes(active)
        result.append({"source_system": key[0], "ticket_id": key[1], "priority": ticket["priority"],
                       "team_id": ticket["team_id"], "current_status": current,
                       "first_response_minutes": first, "resolution_minutes": active_minutes,
                       "response_breached": (age if first is None else first) > Decimal(policy["response_target_minutes"]),
                       "resolution_breached": active_minutes > Decimal(policy["resolution_target_minutes"]),
                       "backlog_age_minutes": None if current == "resolved" else age, "reopened_count": reopens})
    return result
