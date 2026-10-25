# SPDX-License-Identifier: MIT
"""Fail before examples run if the selected executor is not a Mac mini."""

import json
import subprocess
import sys

if sys.platform != "darwin":
    raise SystemExit("A verified Mac mini is required for executable labs.")
result = subprocess.run(["/usr/sbin/system_profiler", "SPHardwareDataType", "-json"],
                        capture_output=True, text=True, check=True, timeout=30)
hardware = json.loads(result.stdout)["SPHardwareDataType"][0]
if hardware.get("machine_name") != "Mac mini":
    raise SystemExit("Hardware mismatch: examples were not executed.")
print(json.dumps({key: hardware.get(key) for key in
                  ("machine_name", "machine_model", "chip_type", "physical_memory")}, indent=2))
