# SPDX-License-Identifier: MIT
"""Exclusive output reservation and atomic evidence checkpoints; no arbitrary overwrite."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

class ReportReservation:

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('x', encoding='utf-8') as handle:
            handle.write('{"status":"reserved_incomplete","schema_version":1}\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.identity = self.path.stat().st_ino

    def write(self, report: dict) -> None:
        if self.path.is_symlink() or self.path.stat().st_ino != self.identity:
            raise FileExistsError('report_reservation_changed')
        raw = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
        fd, name = tempfile.mkstemp(prefix='.northstar-report-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            self.identity = self.path.stat().st_ino
        finally:
            Path(name).unlink(missing_ok=True)

def write_report(path: str | Path, report: dict) -> None:
    ReportReservation(path).write(report)
