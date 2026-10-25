#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check offline Python/SQLite capabilities, without calling a model or network.

This is a preparation diagnostic. It is not an agent implementation, product
test suite, LLM evaluation, or enterprise-readiness assessment.
"""

from __future__ import annotations

import json
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import unittest


def main() -> int:
    checks: dict[str, str] = {}
    if (3, 12) <= sys.version_info[:2] < (3, 15):
        checks["proposed_python_range"] = "pass"
    else:
        checks["proposed_python_range"] = "fail"

    try:
        with tempfile.TemporaryDirectory(prefix="enterprise-agents-readiness-") as tmp:
            path = Path(tmp) / "checkpoint.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE checkpoints (run_id TEXT PRIMARY KEY, step INTEGER)")
                db.execute("INSERT INTO checkpoints VALUES (?, ?)", ("capability-check", 1))
                db.execute("CREATE VIRTUAL TABLE retrieval USING fts5(body)")
                db.execute("INSERT INTO retrieval VALUES (?)", ("approval checkpoint tenant",))
                row = db.execute(
                    "SELECT body FROM retrieval WHERE retrieval MATCH ?", ("approval",)
                ).fetchone()
                checks["sqlite_fts5"] = (
                    "pass" if row == ("approval checkpoint tenant",) else "fail"
                )
            with sqlite3.connect(path) as db:
                row = db.execute(
                    "SELECT step FROM checkpoints WHERE run_id = ?", ("capability-check",)
                ).fetchone()
                checks["sqlite_persistence"] = "pass" if row == (1,) else "fail"
    except sqlite3.Error as exc:
        checks["sqlite_capabilities"] = f"fail: {type(exc).__name__}"

    checks["stdlib_unittest_import"] = "pass" if unittest.TestCase else "fail"
    passed = all(value == "pass" for value in checks.values())
    report = {
        "schema_version": 1,
        "evidence_type": "environment_capability_check",
        "application_tests_run": False,
        "model_calls": 0,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "checks": checks,
        "result": "pass" if passed else "fail",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
