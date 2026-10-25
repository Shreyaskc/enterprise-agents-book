# SPDX-License-Identifier: MIT
"""Run nonempty stdlib tests and optionally save actual execution evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from northstar_agents.cli import write_report
from northstar_agents.evaluation import source_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    count = suite.countTestCases()
    if count == 0:
        raise SystemExit("No tests discovered; refusing empty success")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence = {"schema_version": 1, "artifact_kind": "stdlib_test_execution_report",
                "command": "python scripts/run_tests.py", "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                "source_tree_sha256": source_hash(), "discovered": count, "tests_run": result.testsRun,
                "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
                "successful": result.wasSuccessful(), "live_model_calls": 0,
                "network_policy": "socket connections denied in test process; chapter acceptance subprocesses use the offline wrapper"}
    if args.report:
        write_report(args.report, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
