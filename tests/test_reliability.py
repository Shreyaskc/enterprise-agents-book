# SPDX-License-Identifier: MIT
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest

from northstar_agents.contracts import Rejected, digest
from northstar_agents.data import ROOT
from northstar_agents.reliability import CaseNote, ReliabilityLab, run_lab
from northstar_agents.service import OTHER, PLATFORM, REVIEWER, SERVICE


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        self.lab = ReliabilityLab(directory / "source.sqlite", directory / "destination.sqlite")
        self.note, self.key = CaseNote(), "note-104"

    def tearDown(self):
        self.lab.__exit__()
        self.temp.cleanup()

    def enqueue(self):
        approval = self.lab.approve(SERVICE, self.note)
        self.lab.enqueue(SERVICE, self.note, approval, self.key)
        return approval

    def test_intent_outbox_and_approval_consumption_commit_or_rollback_together(self):
        approval = self.lab.approve(SERVICE, self.note)
        with self.assertRaises(RuntimeError):
            self.lab.enqueue(SERVICE, self.note, approval, self.key, fault="before_intent_commit")
        self.assertEqual(self.lab.counts(SERVICE, self.key), {"source_intents": 0, "source_outbox": 0, "destination_notes": 0})
        self.assertEqual(self.lab.store.db.execute("SELECT used FROM approvals").fetchone()[0], 0)
        self.lab.enqueue(SERVICE, self.note, approval, self.key)
        self.assertEqual(self.lab.counts(SERVICE, self.key), {"source_intents": 1, "source_outbox": 1, "destination_notes": 0})
        self.assertEqual(self.lab.store.db.execute("SELECT used FROM approvals").fetchone()[0], 1)

    def test_note_approval_is_exact_and_dispatch_rechecks_revocation(self):
        approval = self.lab.approve(SERVICE, self.note)
        with self.assertRaisesRegex(Rejected, "approval_payload_mismatch"):
            self.lab.enqueue(SERVICE, replace(self.note, note="changed note"), approval, self.key)
        self.lab.enqueue(SERVICE, self.note, approval, self.key)
        self.lab.store.revoke(PLATFORM, REVIEWER.principal)
        with self.assertRaisesRegex(Rejected, "permission_denied"):
            self.lab.dispatch(SERVICE, self.key)
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 0)

    def test_destination_is_a_separate_database(self):
        with self.assertRaisesRegex(Rejected, "destination_must_be_separate"):
            ReliabilityLab(self.lab.source_path, self.lab.source_path)

    def test_failure_before_destination_commit_is_reconciled_as_absent_then_retried(self):
        self.enqueue()
        with self.assertRaises(RuntimeError):
            self.lab.dispatch(SERVICE, self.key, fault="before_destination_commit")
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 0)
        self.assertEqual(self.lab.reconcile(SERVICE, self.key)["status"], "no_destination_receipt")
        self.assertEqual(self.lab.dispatch(SERVICE, self.key)["status"], "acknowledged")
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)

    def test_timeout_after_destination_commit_reconciles_from_a_new_process(self):
        self.enqueue()
        result = self.lab.dispatch(SERVICE, self.key, fault="timeout_after_destination_commit")
        self.assertEqual(result["status"], "uncertain_reconcile_before_retry")
        self.assertEqual(self.lab.pending(SERVICE, self.key)["state"], "pending")
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)
        code = ("import json,sys; from pathlib import Path; "
                "from northstar_agents.reliability import ReliabilityLab; "
                "from northstar_agents.service import SERVICE;\n"
                "with ReliabilityLab(Path(sys.argv[1]),Path(sys.argv[2])) as lab:\n"
                "    print(json.dumps(lab.reconcile(SERVICE,'note-104')))")
        p = subprocess.run([sys.executable, "-c", code, str(self.lab.source_path), str(self.lab.destination_path)],
                           cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "acknowledged")
        self.assertEqual(self.lab.pending(SERVICE, self.key)["state"], "acknowledged")
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)

    def test_crash_after_response_before_local_receipt_is_reconciled(self):
        self.enqueue()
        with self.assertRaises(RuntimeError):
            self.lab.dispatch(SERVICE, self.key, fault="after_response_before_receipt")
        self.assertEqual(self.lab.pending(SERVICE, self.key)["state"], "pending")
        self.assertEqual(self.lab.reconcile(SERVICE, self.key)["status"], "acknowledged")
        self.assertEqual(self.lab.dispatch(SERVICE, self.key)["status"], "already_acknowledged")
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)

    def test_source_and_destination_both_reject_conflicting_key_reuse(self):
        self.enqueue()
        self.lab.dispatch(SERVICE, self.key)
        conflicting = replace(self.note, note="a different approved note")
        with self.assertRaisesRegex(Rejected, "source_idempotency_conflict"):
            self.lab.enqueue(SERVICE, conflicting, self.lab.approve(SERVICE, conflicting), self.key)
        payload = conflicting.envelope(SERVICE)
        with self.assertRaisesRegex(Rejected, "destination_idempotency_conflict"):
            self.lab.destination.deliver(payload, self.key, digest(payload))
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)

    def test_two_concurrent_dispatchers_share_one_destination_effect(self):
        self.enqueue()
        simultaneous = Barrier(2)
        def dispatch(_):
            with ReliabilityLab(self.lab.source_path, self.lab.destination_path) as worker:
                original = worker.destination.deliver
                def synchronized_deliver(*args, **kwargs):
                    simultaneous.wait(timeout=5)
                    return original(*args, **kwargs)
                worker.destination.deliver = synchronized_deliver
                return worker.dispatch(SERVICE, self.key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(dispatch, range(2)))
        self.assertTrue(all(r["status"] in {"acknowledged", "already_acknowledged"} for r in results))
        self.assertEqual(sorted(r["receipt"]["destination_replayed"] for r in results), [False, True])
        self.assertEqual(self.lab.destination.count(SERVICE, self.key), 1)

    def test_outbox_receipt_and_destination_lookup_are_tenant_scoped(self):
        self.enqueue()
        self.lab.dispatch(SERVICE, self.key)
        with self.assertRaisesRegex(Rejected, "outbox_unavailable"):
            self.lab.pending(OTHER, self.key)
        self.assertIsNone(self.lab.destination.lookup(OTHER, self.key, "0" * 64))

    def test_six_scenario_command_records_observed_success(self):
        report = run_lab()
        self.assertEqual(report["scenario_count"], 6)
        self.assertTrue(report["all_passed"], report)
        self.assertIn("fulfillment unknown", report["note"])
