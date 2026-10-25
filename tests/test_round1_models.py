# SPDX-License-Identifier: MIT
"""Offline robustness observations use doubles; they say nothing about model quality."""
import contextlib, io, json, os, tempfile, unittest, urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from northstar_agents import model_evidence as model
from northstar_agents.adapters import LocalModelApproval, OllamaAdapter, NoRedirect, _http, PLAN_SCHEMA
from northstar_agents.contracts import Rejected
from northstar_agents.reporting import ReportReservation
from northstar_agents.service import SERVICE
from northstar_agents.storage import Store

class ModelEvidenceTests(unittest.TestCase):

    def exercise(self, mode, p, *, failure=None, previous=None, interrupt=False):
        calls = []
        ps = [0]

        def metadata(endpoint, payload=None):
            if endpoint == 'version':
                return {'version': 'test-double'}
            if endpoint == 'tags':
                return {'models': [{'name': 'test-model', 'digest': 'a' * 64, 'size': 1}]}
            if endpoint == 'show':
                return {'license': 'test-double-not-weights'}
            if endpoint == 'ps':
                ps[0] += 1
                if ps[0] > 1 and failure == 'url':
                    raise urllib.error.URLError('PRIVATE_PATH_CANARY')
                if ps[0] > 1 and failure == 'json':
                    raise json.JSONDecodeError('PRIVATE_PATH_CANARY', '', 0)
                return {'models': []}

        class FakeAdapter:

            def __init__(self, store, *, on_reserved):
                self.store, self.reserved = (store, on_reserved)

            def plan(self, ctx, prompt, approval):
                self.store.reserve(ctx, 'model-' + approval.approval_id, 3)
                self.reserved()
                call = model.CASES[len(calls)]['expected']
                calls.append(call)
                return {'tool_call': call, 'usage_reported': {'prompt_eval_count': 1, 'eval_count': 1}}
        original = ReportReservation.write
        interrupted = [False]

        def write(reservation, report):
            original(reservation, report)
            if interrupt and report['sample_count'] == 1 and (not interrupted[0]):
                interrupted[0] = True
                raise KeyboardInterrupt
        env = {} if previous is None else {'NORTHSTAR_ENABLE_LOCAL_MODEL': previous}
        with patch.dict(os.environ, env, clear=True), patch('runpy.run_path', return_value={}), patch.object(ReportReservation, 'write', write), contextlib.redirect_stdout(io.StringIO()):
            status = model.run(mode, metadata_reader=metadata, adapter_type=FakeAdapter, argv=['--model', 'test-model', '--expected-digest', 'a' * 64, '--output', str(p), '--approve-local-inference'])
            self.assertEqual(os.environ.get('NORTHSTAR_ENABLE_LOCAL_MODEL'), previous)
        return (status, json.loads(p.read_text()), calls)

    def test_completed_reports_survive_postflight_url_and_json_failure_for_both_scripts_and_env_states(self):
        for mode in ['smoke', 'agent']:
            for fault in ['url', 'json']:
                for previous in [None, 'preexisting-value']:
                    with self.subTest(mode=mode, fault=fault, previous=previous), tempfile.TemporaryDirectory() as tmp:
                        status, report, calls = self.exercise(mode, Path(tmp) / 'evidence.json', failure=fault, previous=previous)
                        self.assertEqual(status, 0, report)
                        self.assertEqual(len(calls), 3)
                        self.assertEqual(report['reservations'], 3)
                        self.assertEqual(len(report['attempts']), 3)
                        self.assertTrue(all(len(a['prompt_sha256']) == 64 and a['schema_sha256'] == report['proposal_schema_sha256'] for a in report['attempts']))
                        self.assertTrue(report['measured_elapsed_within_90_seconds'])
                        self.assertTrue(report['completed'])
                        self.assertTrue(report['environment_restored'])
                        self.assertEqual(report['postflight_status'], 'unknown')
                        self.assertIsNone(report['loaded_models_after'])
                        self.assertNotIn('PRIVATE_PATH_CANARY', json.dumps(report))
                        with Store(Path(tmp) / 'evidence.budget.sqlite') as store:
                            self.assertEqual(store.db.execute('SELECT sum(used) FROM budgets WHERE run_id LIKE "model-%"').fetchone()[0], 3)

    def test_interrupt_after_first_completed_request_retains_partial_report_without_retry(self):
        for mode in ['smoke', 'agent']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                status, report, calls = self.exercise(mode, Path(tmp) / 'evidence.json', interrupt=True)
                self.assertEqual(status, 130)
                self.assertEqual(len(calls), 1)
                self.assertEqual(report['sample_count'], 1)
                self.assertEqual(report['attempts_started'], 1)
                self.assertFalse(report['completed'])
                self.assertEqual(report['status'], 'interrupted_incomplete')
                self.assertTrue(report['environment_restored'])

    def test_adapter_schema_outer_shape_usage_and_transport_failures_do_not_retry(self):
        for response in [[], None, True, {'done': True, 'model': 'test', 'message': {'content': 'not-json'}}, {'done': True, 'model': 'test', 'message': {'content': '{}'}, 'eval_count': True}, {'done': True, 'model': 'test', 'eval_count': -1}, {'done': True, 'model': 'test', 'eval_count': 129}]:
            with self.subTest(response=response), Store() as store, patch.dict(os.environ, {'NORTHSTAR_ENABLE_LOCAL_MODEL': '1'}):
                calls = []
                approval = LocalModelApproval('test', SERVICE.tenant, SERVICE.principal, 'test', 'a' * 64, 'test', store.now() + 30)

                def transport(payload):
                    calls.append(payload)
                    return response
                adapter = OllamaAdapter(store, transport)
                with self.assertRaises(Rejected):
                    adapter.plan(SERVICE, 'question', approval)
                self.assertEqual(len(calls), 1)
                with self.assertRaisesRegex(Rejected, 'budget_exhausted'):
                    adapter.plan(SERVICE, 'retry', approval)
                self.assertEqual(len(calls), 1)

    def test_transport_ambiguity_remains_reserved_across_store_reopen_and_expiry_never_calls(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'NORTHSTAR_ENABLE_LOCAL_MODEL': '1'}):
            path = Path(tmp) / 'state.sqlite'
            with Store(path) as store:
                approval = LocalModelApproval('same-key', SERVICE.tenant, SERVICE.principal, 'test', 'a' * 64, 'test', store.now() + 30)
                with self.assertRaises(TimeoutError):
                    OllamaAdapter(store, lambda _: (_ for _ in ()).throw(TimeoutError())).plan(SERVICE, 'question', approval)
            with Store(path) as store:
                adapter = OllamaAdapter(store, lambda _: self.fail('must not call'))
                with self.assertRaisesRegex(Rejected, 'budget_exhausted'):
                    adapter.plan(SERVICE, 'retry', approval)
                with self.assertRaisesRegex(Rejected, 'model_approval_expired'):
                    adapter.plan(SERVICE, 'expired', replace(approval, expires_at=0))

    def test_http_invalid_json_oversize_and_redirect_are_stable(self):
        for raw in [b'not JSON', b'x' * 65537]:
            response = unittest.mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = raw
            opener = unittest.mock.MagicMock()
            opener.open.return_value = response
            with patch('urllib.request.build_opener', return_value=opener), self.assertRaises(Rejected):
                _http({})
        with self.assertRaisesRegex(Rejected, 'model_redirect_denied'):
            NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_identifier_schema_and_parser_constraints_agree(self):
        for variant in PLAN_SCHEMA['oneOf']:
            argument = variant['properties']['arguments']
            key = argument['required'][0]
            rule = argument['properties'][key]
            self.assertEqual(rule['maxLength'], 240 if key == 'query' else 80)
            self.assertIn('pattern', rule)
            self.assertEqual(rule['minLength'], 1)

@unittest.skipUnless(os.environ.get('NORTHSTAR_TEST_LOOPBACK') == '1', 'Explicit finite loopback HTTP fixture opt-in required')
class SocketTimeoutEvidenceTests(unittest.TestCase):

    def test_finite_loopback_delays_show_inactivity_timeout_is_not_absolute_deadline(self):
        import subprocess, sys
        from northstar_agents.data import ROOT
        run = subprocess.run([sys.executable, 'tests/http_timeout_fixture.py'], cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        rows = report['results']
        self.assertTrue(all((r['fixture_thread_stopped'] for r in rows)))
        self.assertTrue(all((r['error_type'] is not None for r in rows[:2])))
        self.assertIsNone(rows[2]['error_type'])
        self.assertGreater(rows[2]['observed_elapsed_seconds'], 0.05)
        self.assertFalse(report['server_cancellation_claimed'])
