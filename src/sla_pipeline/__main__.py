import argparse
import copy
import csv
import json
import sys
from pathlib import Path

from .model import AS_OF, empty_state, metrics, prepare, read_batch


def write_metrics(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [
            "source_system", "ticket_id", "priority", "team_id", "current_status", "first_response_minutes",
            "resolution_minutes", "response_breached", "resolution_breached", "backlog_age_minutes", "reopened_count"])
        writer.writeheader()
        writer.writerows(rows)


def demo(directory, output, as_of):
    """Offline behavior demo; does not imply that PostgreSQL or KNIME ran."""
    batch = read_batch(directory)
    if not batch["tickets"]:
        raise ValueError("The failure/correction demo requires at least one ticket")
    state = empty_state()
    runs = []
    invalid = copy.deepcopy(batch)
    invalid["tickets"][0]["priority"] = "P9"
    for name, incoming in (("failed_bad_priority", invalid), ("corrected_load", batch), ("identical_rerun", batch)):
        state, rejected, counts = prepare(incoming, state, as_of)
        runs.append({"step": name, "status": "failed" if rejected else "succeeded", **counts, "rejections": rejected})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "run_log.json").write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    write_metrics(output / "ticket_metrics.csv", metrics(state, as_of))
    print(json.dumps({"mode": "offline Python oracle (not PostgreSQL or KNIME)", "as_of": as_of,
                      "output": str(output), "runs": [{k: v for k, v in r.items() if k != "rejections"} for r in runs]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="From Support Tickets to Trusted SLA Metrics")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Write seeded, entirely fictional input CSVs")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--tickets", type=int, default=100)
    validate = commands.add_parser("validate", help="Validate a complete standalone batch offline")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--as-of", default=AS_OF)
    local = commands.add_parser("demo", help="Offline failed/corrected/replayed load demonstration")
    local.add_argument("--input", type=Path, default=Path("data/sample"))
    local.add_argument("--output", type=Path, default=Path("build/demo"))
    local.add_argument("--as-of", default=AS_OF)
    commands.add_parser("init-db", help="Create PostgreSQL schemas and analytics function")
    load = commands.add_parser("load", help="Audit, validate and atomically upsert into PostgreSQL")
    load.add_argument("--input", type=Path, required=True)
    load.add_argument("--as-of", default=AS_OF)
    report = commands.add_parser("metrics", help="Query the PostgreSQL analytics function")
    report.add_argument("--as-of", default=AS_OF)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            from .generate import generate as create
            create(args.output, args.seed, args.tickets)
            print(f"Fictional inputs written to {args.output}; seed={args.seed}")
        elif args.command == "validate":
            _, rejected, counts = prepare(read_batch(args.input), empty_state(), args.as_of)
            print(json.dumps({"mode": "offline validation (projected counters; no database writes)",
                              **counts, "rejections": rejected}, indent=2))
            return 1 if rejected else 0
        elif args.command == "demo":
            demo(args.input, args.output, args.as_of)
        else:
            from . import postgres
            if args.command == "init-db":
                postgres.initialize()
                print("PostgreSQL schemas and analytics function initialized")
            elif args.command == "load":
                result = postgres.load(read_batch(args.input), args.as_of)
                print(json.dumps(result, indent=2))
                return 1 if result["status"] == "failed" else 0
            elif args.command == "metrics":
                write_metrics(args.output, postgres.query_metrics(args.as_of))
                print(f"PostgreSQL metrics written to {args.output}")
    except (ValueError, RuntimeError, OSError, KeyError, ImportError) as exc:
        # Deliberately omit arbitrary errors which might contain connection secrets.
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc), file=sys.stderr)
        elif isinstance(exc, ImportError):
            print('PostgreSQL driver unavailable; run pip install -e ".[postgres]"', file=sys.stderr)
        elif isinstance(exc, KeyError):
            print("Missing configuration (set DATABASE_URL for database commands)", file=sys.stderr)
        else:
            print(f"File or connection operation failed ({type(exc).__name__}); check inputs and configuration", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
