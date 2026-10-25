# SPDX-License-Identifier: MIT
"""Default tests may not open network connections."""

import sys


def _deny_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise PermissionError("network_disabled_in_core_tests")


sys.addaudithook(_deny_network)
