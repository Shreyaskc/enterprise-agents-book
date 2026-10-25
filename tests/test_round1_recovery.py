# SPDX-License-Identifier: MIT
"""Confirmed Round 1 failures: authorization for effects differs from receipt recovery."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from northstar_agents.contracts import Rejected, digest
from northstar_agents.reliability import CaseNote, ReliabilityLab, run_lab
from northstar_agents.service import Northstar, SERVICE, REVIEWER, PLATFORM
from northstar_agents.storage import Store

class ReceiptRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.clock = [1000]
        self.lab = ReliabilityLab(self.p / 'source.sqlite', self.p / 'destination.sqlite')
        self.addCleanup(lambda: self.lab.__exit__())
        self.lab.store.now = lambda: self.clock[0]
        self.note = CaseNote()
        self.grant = self.lab.approve(SERVICE, self.note)
        self.lab.enqueue(SERVICE, self.note, self.grant, 'A')

    def reopen(self):
        self.lab.__exit__()
        self.lab = ReliabilityLab(self.p / 'source.sqlite', self.p / 'destination.sqlite')
        self.lab.store.now = lambda: self.clock[0]

    def test_expired_committed_recovery_after_reopen_never_delivers(self):
        self.lab.dispatch(SERVICE, 'A', fault='timeout_after_destination_commit')
        self.clock[0] = 1301
        self.reopen()
        with patch.object(self.lab.destination, 'deliver', side_effect=AssertionError('no new effect')):
            self.assertEqual(self.lab.reconcile(SERVICE, 'A')['status'], 'acknowledged')
            self.assertEqual(self.lab.dispatch(SERVICE, 'A')['status'], 'already_acknowledged')
        self.assertEqual(self.lab.counts(SERVICE, 'A')['destination_notes'], 1)

    def test_expiry_between_destination_commit_and_acknowledgement(self):
        original = self.lab.destination.deliver

        def late(*a, **kw):
            receipt = original(*a, **kw)
            self.clock[0] = 1301
            return receipt
        with patch.object(self.lab.destination, 'deliver', late):
            self.assertEqual(self.lab.dispatch(SERVICE, 'A')['status'], 'acknowledged')

    def test_expired_absent_effect_requires_key_bound_fresh_reauthorization(self):
        self.lab.enqueue(SERVICE, self.note, self.lab.approve(SERVICE, self.note), 'B')
        self.clock[0] = 1301
        with patch.object(self.lab.destination, 'deliver', side_effect=AssertionError('no effect')):
            self.assertEqual(self.lab.reconcile(SERVICE, 'A')['status'], 'no_destination_receipt')
            with self.assertRaisesRegex(Rejected, 'approval_unavailable'):
                self.lab.dispatch(SERVICE, 'A')
        grant = self.lab.approve(SERVICE, self.note)
        self.lab.reauthorize(SERVICE, 'A', grant)
        with self.assertRaisesRegex(Rejected, 'approval_unavailable'):
            self.lab.reauthorize(SERVICE, 'B', grant)
        self.assertEqual(self.lab.dispatch(SERVICE, 'A')['status'], 'acknowledged')
        changed = replace(self.note, note='different payload')
        g = self.lab.approve(SERVICE, changed)
        with self.assertRaisesRegex(Rejected, 'approval_payload_mismatch'):
            self.lab.reauthorize(SERVICE, 'B', g)
        self.assertEqual(self.lab.counts(SERVICE, 'B')['destination_notes'], 0)

    def test_revoked_reviewer_does_not_block_receipt_recovery_but_blocks_new_effect(self):
        self.lab.dispatch(SERVICE, 'A', fault='timeout_after_destination_commit')
        self.lab.store.revoke(PLATFORM, REVIEWER.principal)
        self.assertEqual(self.lab.reconcile(SERVICE, 'A')['status'], 'acknowledged')
        self.assertEqual(self.lab.dispatch(SERVICE, 'A')['status'], 'already_acknowledged')

    def test_current_reader_revocation_blocks_recovery_without_state_change(self):
        self.lab.dispatch(SERVICE, 'A', fault='timeout_after_destination_commit')
        self.lab.store.revoke(PLATFORM, SERVICE.principal)
        with self.assertRaisesRegex(Rejected, 'permission_denied'):
            self.lab.reconcile(SERVICE, 'A')
        self.assertEqual(self.lab.store.db.execute('SELECT state FROM note_outbox').fetchone()[0], 'pending')
        self.assertEqual(self.lab.destination.count(SERVICE, 'A'), 1)

    def test_policy_change_preserves_committed_recovery_and_denies_uncommitted_dispatch(self):
        self.lab.enqueue(SERVICE, self.note, self.lab.approve(SERVICE, self.note), 'B')
        self.lab.dispatch(SERVICE, 'A', fault='timeout_after_destination_commit')
        self.lab.store.fixture['policy_version'] = 'v4'
        self.assertEqual(self.lab.reconcile(SERVICE, 'A')['status'], 'acknowledged')
        with self.assertRaisesRegex(Rejected, 'stale_policy'):
            self.lab.dispatch(SERVICE, 'B')
        self.assertIn('manual review', self.lab.reconcile(SERVICE, 'B')['next_step'])

    def test_receipts_bind_full_identity_not_just_identical_payload(self):
        self.lab.enqueue(SERVICE, self.note, self.lab.approve(SERVICE, self.note), 'B')
        a = self.lab.dispatch(SERVICE, 'A')['receipt']
        h = digest(self.note.envelope(SERVICE))
        for receipt in [None, {}, a, {**a, 'request_key': 'B', 'tenant': 'harbor'}, {**a, 'request_key': 'B', 'destination_note_id': 'NOTE-wrong'}, {**a, 'request_key': 'B', 'payload_hash': '0' * 64}]:
            with self.subTest(receipt=receipt), self.assertRaises(Rejected):
                self.lab.acknowledge(SERVICE, 'B', h, receipt)
            self.assertEqual(self.lab.pending(SERVICE, 'B')['state'], 'pending')
        b = self.lab.dispatch(SERVICE, 'B')['receipt']
        self.assertEqual(self.lab.acknowledge(SERVICE, 'B', h, b)['status'], 'acknowledged')
        self.assertEqual(self.lab.destination.count(SERVICE, 'B'), 1)

    def test_fabricated_receipt_without_destination_commit_is_not_accepted(self):
        h = digest(self.note.envelope(SERVICE))
        import hashlib
        receipt = {'tenant': SERVICE.tenant, 'request_key': 'A', 'payload_hash': h, 'destination_note_id': 'NOTE-' + hashlib.sha256(b'northstar:A').hexdigest()[:12], 'status': 'stored_in_simulated_destination'}
        with self.assertRaisesRegex(Rejected, 'unverified_destination_receipt'):
            self.lab.acknowledge(SERVICE, 'A', h, receipt)
        self.assertEqual(self.lab.pending(SERVICE, 'A')['state'], 'pending')

    def test_outbox_acceptance_rejects_omitted_ack_even_when_counts_are_one(self):

        def omit(self, ctx, key, h, receipt):
            return {'status': 'acknowledged', 'receipt': receipt}
        with patch.object(ReliabilityLab, 'acknowledge', omit):
            report = run_lab()
        self.assertFalse(report['all_passed'])
        self.assertTrue(all((not r['passed'] and r['observed_final']['destination_notes'] == 1 and (r['observed_final']['source_state'] == 'pending') for r in report['results'][:4])))

class LocalReceiptTests(unittest.TestCase):

    def test_committed_local_receipt_survives_policy_change_but_current_access_is_required(self):
        with Store() as store:
            app = Northstar(store)
            action = app.propose()
            grant = app.approve(REVIEWER, SERVICE, action)
            first = app.execute(SERVICE, action, grant, 'A')
            store.fixture['policy_version'] = 'v4'
            store.revoke(PLATFORM, REVIEWER.principal)
            replay = app.execute(SERVICE, action, grant, 'A')
            self.assertTrue(replay['replayed'])
            self.assertEqual(first['local_case_id'], replay['local_case_id'])
            with self.assertRaisesRegex(Rejected, 'stale_policy'):
                app.execute(SERVICE, action, grant, 'B')
            store.revoke(PLATFORM, SERVICE.principal)
            with self.assertRaisesRegex(Rejected, 'permission_denied'):
                app.execute(SERVICE, action, grant, 'A')
            self.assertEqual(store.db.execute('SELECT count(*) FROM local_cases').fetchone()[0], 1)

    def test_completed_checkpoint_is_historical_and_does_not_authorize_new_effect(self):
        with Store() as store:
            app = Northstar(store)
            app.workflow(SERVICE, 'A')
            store.fixture['policy_version'] = 'v4'
            row = store.db.execute('SELECT permissions FROM principals WHERE tenant=? AND principal=?', (SERVICE.tenant, SERVICE.principal)).fetchone()
            permissions = json.loads(row[0])
            permissions.remove('invoice.read')
            permissions.remove('case.propose')
            store.db.execute('UPDATE principals SET permissions=? WHERE tenant=? AND principal=?', (json.dumps(permissions), SERVICE.tenant, SERVICE.principal))
            output = app.workflow(SERVICE, 'A')
            self.assertFalse(output['policy_current'])
            self.assertEqual(output['result_kind'], 'historical_read_only_checkpoint')
            self.assertTrue(output['fresh_action_authorization_required'])
            with self.assertRaises(Rejected):
                app.propose()
            self.assertEqual(store.db.execute('SELECT count(*) FROM local_cases').fetchone()[0], 0)
