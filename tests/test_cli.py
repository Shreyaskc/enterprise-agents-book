# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from northstar_agents.cli import STAGES
from northstar_agents.data import ROOT


class LabAcceptanceTests(unittest.TestCase):
    def test_every_offline_lab_command_under_network_denial(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                p = subprocess.run([sys.executable, "scripts/run_offline.py", stage], cwd=ROOT,
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr)
                result = json.loads(p.stdout)
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(result["execution_mode"], "deterministic_simulation")
                if stage == "capstone":
                    self.assertTrue(result["regression"]["all_passed"])
                    self.assertFalse(result["production_ready"])
                if stage == "memory":
                    self.assertEqual(result["branch_policy_version"], "v4")
                    self.assertEqual(result["canonical_policy_version"], "v3")
                if stage == "durability-lab":
                    self.assertTrue(result["all_passed"])
                    self.assertEqual(result["scenario_count"], 6)

    def test_cli_budget_error_is_machine_readable_without_traceback(self):
        p = subprocess.run([sys.executable, "-m", "northstar_agents", "agent", "--maximum-steps", "0"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(json.loads(p.stderr)["code"], "budget_exhausted")
        self.assertNotIn("Traceback", p.stderr)

    def test_report_is_written_and_existing_user_file_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            p = subprocess.run([sys.executable, "scripts/run_offline.py", "evaluate", "--output", str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(output.read_text())["all_passed"])
            output.write_text("user's existing content")
            p = subprocess.run([sys.executable, "-m", "northstar_agents", "evaluate", "--output", str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(output.read_text(), "user's existing content")

    def test_lab_contract_has_twelve_labs_and_real_commands(self):
        contract = json.loads((ROOT / "docs/lab-index.json").read_text())["labs"]
        self.assertEqual([c["lab"] for c in contract], list(range(1, 13)))
        for lab in contract:
            self.assertIn(lab["stage"], STAGES)
            self.assertTrue(lab["command"].startswith("python -m northstar_agents "))
