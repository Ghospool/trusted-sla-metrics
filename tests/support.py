import csv
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
AS_OF = "2025-01-08T00:00:00Z"
HEADERS = {
    "teams": ("team_id", "team_name", "staffing_count"),
    "policies": ("priority", "response_target_minutes", "resolution_target_minutes"),
    "tickets": ("source_system", "ticket_id", "created_at", "priority", "team_id", "subject"),
    "events": ("source_system", "event_id", "ticket_id", "occurred_at", "event_type"),
}
NUMERIC = {"first_response_minutes", "resolution_minutes", "backlog_age_minutes", "reopened_count"}
BOOLEAN = {"response_breached", "resolution_breached"}
METRIC_FIELDS = ("source_system", "ticket_id", "current_status", "first_response_minutes",
                 "resolution_minutes", "response_breached", "resolution_breached",
                 "backlog_age_minutes", "reopened_count")


def expected_rows(filename):
    with (ROOT / "data" / "expected" / filename).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def normalized_metrics(rows):
    result = {}
    for row in rows:
        values = dict(row)
        if "status" in values:
            values["current_status"] = values.pop("status")
        normalized = {}
        for field in METRIC_FIELDS:
            value = values[field]
            if value is None or value == "":
                normalized[field] = None
            elif field in BOOLEAN:
                if isinstance(value, bool):
                    normalized[field] = value
                elif str(value).lower() in {"true", "false"}:
                    normalized[field] = str(value).lower() == "true"
                else:
                    raise ValueError(f"Not a boolean: {value!r}")
            elif field in NUMERIC:
                normalized[field] = Decimal(str(value))
            else:
                normalized[field] = value
        key = (values["source_system"], values["ticket_id"])
        if key in result:
            raise AssertionError(f"Duplicate metric identity: {key}")
        result[key] = normalized
    return result


def write_batch(directory, batch):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for entity, fields in HEADERS.items():
        with (directory / f"{entity}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(batch[entity])


def event(event_id, kind, moment, ticket_id="T001", source="atlas_service"):
    return {"source_system": source, "event_id": event_id, "ticket_id": ticket_id,
            "occurred_at": moment, "event_type": kind}
