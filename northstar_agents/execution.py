# SPDX-License-Identifier: MIT
"""Bound local child execution. Diagnostics are codes, never echoed child secrets."""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

def run_bounded(command: list[str], *, cwd: Path, timeout: float=60, env: dict | None=None) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        except OSError:
            return {'exit_code': None, 'error': 'launch_failed', 'stdout': '', 'duration_seconds': time.monotonic() - started}
        error = None
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            error, code = ('command_timeout', None)
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout.seek(0)
        raw = stdout.read(1000001)
        if len(raw) > 1000000:
            error, raw = ('output_too_large', b'')
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            error, content = ('invalid_output_encoding', '')
    return {'exit_code': code, 'error': error, 'stdout': content, 'duration_seconds': round(time.monotonic() - started, 6)}
