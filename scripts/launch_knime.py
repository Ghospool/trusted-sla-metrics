"""Launch local KNIME with session-only credentials for the fictional SLA demo."""

import argparse
import csv
import getpass
import io
import os
from pathlib import Path
import subprocess
import sys
import warnings


DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/trusted_sla_demo"


def knime_running():
    processes = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32" / "tasklist.exe"),
         "/FI", "IMAGENAME eq knime.exe", "/FO", "CSV", "/NH"],
        capture_output=True, check=True,
    )
    rows = csv.reader(io.StringIO(processes.stdout.decode("mbcs")))
    return any(row and row[0].lower() == "knime.exe" for row in rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knime", type=Path, default=Path(r"C:\Program Files\KNIME\knime.exe"))
    parser.add_argument("--workspace", type=Path, default=Path.home() / "knime-workspace")
    parser.add_argument("--check", action="store_true", help="Check paths and running processes without prompting or launching")
    args = parser.parse_args(argv)

    if os.name != "nt":
        parser.error("This launcher requires Windows.")
    knime = args.knime.resolve()
    workspace = args.workspace.resolve()
    if not knime.is_file() or knime.name.lower() != "knime.exe":
        parser.error("Provide an existing knime.exe using --knime.")
    if not workspace.is_dir():
        parser.error("Provide your existing KNIME workspace directory using --workspace.")

    try:
        running = knime_running()
    except (OSError, subprocess.SubprocessError, UnicodeError, KeyError):
        print("Could not check running KNIME processes; no launch attempted.", file=sys.stderr)
        return 1

    print(f"KNIME executable: {knime}")
    print(f"Workspace: {workspace}")
    print("Database: trusted_sla_demo on 127.0.0.1:5432; user postgres")
    if args.check:
        print(f"Path checks passed. KNIME already running: {'yes' if running else 'no'}.")
        return 0
    if running:
        print("Save and close all KNIME windows before launching. No password requested.", file=sys.stderr)
        return 1

    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = DATABASE_URL
    child_env.pop("PGPASSWORD", None)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            child_env["PGPASSWORD"] = getpass.getpass("Local PostgreSQL password (hidden): ")
        if not child_env["PGPASSWORD"]:
            print("Empty password; no launch attempted.", file=sys.stderr)
            return 1
        if knime_running():
            print("KNIME started during password entry. Close it before trying again.", file=sys.stderr)
            return 1
        subprocess.Popen([str(knime), "-data", str(workspace)], cwd=knime.parent,
                         env=child_env, close_fds=True)
    except getpass.GetPassWarning:
        print("Hidden password entry unavailable. Run from an interactive Command Prompt.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no launch attempted.", file=sys.stderr)
        return 130
    except (OSError, subprocess.SubprocessError, UnicodeError, KeyError):
        print("Could not confirm process state or start KNIME; no credentials were written to a file.", file=sys.stderr)
        return 1
    finally:
        child_env.pop("PGPASSWORD", None)

    print("KNIME launch requested. No database load was performed.")
    print("The password is inherited by KNIME and its child processes, not stored in the workflow.")
    print("Close KNIME and its child processes when finished to end this credential session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
