# SPDX-License-Identifier: MIT
"""Deny socket connections in this process, then run the chapter CLI."""

from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def audit(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise PermissionError("network_disabled_for_offline_acceptance")


sys.addaudithook(audit)
runpy.run_module("northstar_agents", run_name="__main__")
