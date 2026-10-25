# SPDX-License-Identifier: MIT
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from northstar_agents.acceptance import semantic_checks
from northstar_agents.cli import main
from northstar_agents.contracts import Rejected
from northstar_agents.coverage import load_contract
from northstar_agents.data import ROOT
from northstar_agents.evaluation import evaluate
from northstar_agents.execution import run_bounded
from northstar_agents.provenance import git_metadata
from northstar_agents.reporting import ReportReservation
from northstar_agents.service import Northstar
from northstar_agents.storage import Store

def copy_source(path):
    shutil.copytree(ROOT, path, ignore=shutil.ignore_patterns('.git', '__pycache__', '.state', 'artifacts', '*.pyc'))
    return path

class ContractTests(unittest.TestCase):

    def test_invalid_regression_contracts_are_rejected_before_observation(self):
        original = json.loads((ROOT / 'evals/cases/regression.json').read_text())
        variants = [[], {}, {'schema_version': 1, 'contract_kind': 'regression', 'cases': []}]
        for mode in ['missing', 'duplicate', 'schema']:
            value = copy.deepcopy(original)
            if mode == 'missing':
                value['cases'].pop()
            elif mode == 'duplicate':
                value['cases'][-1] = value['cases'][0]
            else:
                value['schema_version'] = 2
            variants.append(value)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'evals/cases').mkdir(parents=True)
            for value in variants:
                (root / 'evals/cases/regression.json').write_text(json.dumps(value))
                with patch('northstar_agents.evaluation.ROOT', root), patch('northstar_agents.evaluation.observe', side_effect=AssertionError('must not execute')):
                    report = evaluate()
                self.assertEqual(report['status'], 'invalid_contract')
                self.assertFalse(report['all_passed'])
                self.assertEqual(report['sample_count'], 0)

    def test_invalid_lab_contracts_persist_failure_without_execution(self):
        verify = runpy.run_path(str(ROOT / 'scripts/verify_labs.py'))['verify']
        original = json.loads((ROOT / 'docs/lab-index.json').read_text())
        variants = [[], {}, {**original, 'labs': []}]
        for mode in ['missing', 'duplicate', 'resume', 'outbox', 'schema']:
            value = copy.deepcopy(original)
            if mode == 'missing':
                value['labs'].pop()
            elif mode == 'duplicate':
                value['labs'][-1] = value['labs'][0]
            elif mode in ['resume', 'outbox']:
                value['labs'][5].pop('resume_command' if mode == 'resume' else 'reliability_command')
            else:
                value['schema_version'] = '1'
            variants.append(value)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for i, value in enumerate(variants):
                contract = p / f'contract-{i}.json'
                contract.write_text(json.dumps(value))
                report = verify(p / f'report-{i}.json', contract_path=contract, runner=lambda *a, **kw: self.fail('must not run'))
                self.assertEqual(report['status'], 'invalid_contract')
                self.assertEqual(report['commands_run'], 0)
                self.assertFalse(report['all_passed'])

    def test_semantics_reject_envelope_preserving_business_mutations(self):
        for stage, mutate in [('baseline', lambda d: d.update(invoice_total_gbp='999.00')), ('retrieve', lambda d: d['evidence'][0].pop('source')), ('memory', lambda d: d.update(harbor_view={'status': 'fresh', 'value': 'LEAK'})), ('memory', lambda d: d.update(after_deletion={'status': 'fresh', 'value': 'NOT_DELETED'})), ('approvals', lambda d: d.update(local_mutations=2)), ('platform', lambda d: d.update(cross_tenant_invoice_denied=False)), ('teams', lambda d: d['inventory_operations'].update(purchase_authorized=True))]:
            with self.subTest(stage=stage):
                p = subprocess.run([sys.executable, 'scripts/run_offline.py', stage], cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(p.returncode, 0, p.stderr)
                output = json.loads(p.stdout)
                self.assertTrue(semantic_checks(stage, output))
                mutate(output)
                self.assertFalse(semantic_checks(stage, output))

class ReportTests(unittest.TestCase):

    def test_occupied_capstone_report_is_rejected_before_database_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            report = p / 'report.json'
            report.write_text('KEEP_CANARY')
            db = p / 'state.sqlite'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = main(['capstone', '--db', str(db), '--report', str(report)])
            self.assertEqual(status, 2)
            self.assertEqual(report.read_text(), 'KEEP_CANARY')
            self.assertFalse(db.exists())

    def test_report_failure_after_commit_returns_receipt_and_replay_has_one_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            out = io.StringIO()
            with patch.object(ReportReservation, 'write', side_effect=OSError('injected')), contextlib.redirect_stdout(out):
                status = main(['capstone', '--db', str(p / 's.sqlite'), '--report', str(p / 'r.json')])
            self.assertEqual(status, 3)
            result = json.loads(out.getvalue())
            self.assertEqual(result['status'], 'result_available_report_failed')
            case_id = result['result']['local_action']['local_case_id']
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['capstone', '--db', str(p / 's.sqlite'), '--report', str(p / 'retry.json')]), 0)
            replay = json.loads(out.getvalue())
            self.assertTrue(replay['local_action']['replayed'])
            self.assertEqual(case_id, replay['local_action']['local_case_id'])
            with Store(p / 's.sqlite') as store:
                self.assertEqual(store.db.execute('SELECT count(*) FROM local_cases').fetchone()[0], 1)

    def test_atomic_report_preserves_existing_and_reservation_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.json'
            r = ReportReservation(p)
            r.write({'status': 'first'})
            r.write({'status': 'second'})
            self.assertEqual(json.loads(p.read_text())['status'], 'second')
            with self.assertRaises(FileExistsError):
                ReportReservation(p)
            p.unlink()
            p.write_text('OTHER')
            with self.assertRaises(FileExistsError):
                r.write({'status': 'wrong'})
            self.assertEqual(p.read_text(), 'OTHER')

class ProvenanceAndSourceTests(unittest.TestCase):

    def test_optional_git_missing_ancestor_and_stall_are_not_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            root = p / 'lab'
            root.mkdir()
            with patch('shutil.which', return_value=None):
                self.assertEqual(git_metadata(root)['git_metadata_reason'], 'git_unavailable')
            self.assertEqual(git_metadata(root)['git_revision'], None)
            (root / '.git').mkdir()
            fake = p / 'git'
            fake.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(30)\n')
            fake.chmod(448)
            with patch('shutil.which', return_value=str(fake)):
                result = git_metadata(root)
            self.assertIsNone(result['git_revision'])
            self.assertIsNone(result['worktree_clean'])
            self.assertEqual(result['git_metadata_reason'], 'command_timeout')

    def test_no_git_evaluate_and_capstone_cli_succeed_in_fresh_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_source(Path(tmp) / 'lab')
            for stage in ['evaluate', 'capstone']:
                p = subprocess.run([sys.executable, '-m', 'northstar_agents', stage], cwd=root, env={**os.environ, 'PYTHONPATH': '', 'PATH': '/not/git'}, capture_output=True, text=True, timeout=20)
                self.assertEqual(p.returncode, 0, p.stderr)
                output = json.loads(p.stdout)
                report = output if stage == 'evaluate' else output['regression']
                self.assertIsNone(report['git_revision'])
                self.assertEqual(report['git_metadata_reason'], 'git_unavailable')

    def test_archive_checker_ignores_unrelated_parent_and_has_nonempty_exact_lab_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(p)], check=True, timeout=5)
            (p / 'UNRELATED_CANARY.txt').write_text('PRIVATE_CANARY')
            root = copy_source(p / 'lab')
            run = subprocess.run([sys.executable, 'scripts/check_repository.py'], cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            output = json.loads(run.stdout)
            self.assertGreater(output['files_checked'], 47)
            self.assertEqual(output['files_checked'], len(output['source_files']))
            self.assertNotIn('UNRELATED_CANARY.txt', output['source_files'])
            self.assertTrue(all((n > 0 for n in output['checks_executed'].values())))
            self.assertIsNone(git_metadata(root)['git_revision'])

    def test_checker_rejects_syntax_json_link_fixture_and_wrong_root_faults(self):
        for fault in ['syntax', 'json', 'link', 'fixture', 'root']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = copy_source(Path(tmp) / 'lab')
                if fault == 'syntax':
                    (root / 'northstar_agents/__init__.py').write_text('def broken(')
                elif fault == 'json':
                    (root / 'evals/cases/regression.json').write_text('{')
                elif fault == 'link':
                    (root / 'README.md').write_text('[missing](missing-file.md)')
                elif fault == 'fixture':
                    (root / 'data/fixtures/northstar_synthetic.json').write_text('{}')
                else:
                    (root / 'pyproject.toml').write_text('[project]\nname="unrelated"')
                run = subprocess.run([sys.executable, 'scripts/check_repository.py'], cwd=root, capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(json.loads(run.stdout)['status'], 'fail')
                self.assertNotIn('Traceback', run.stderr)

class BoundedVerifierTests(unittest.TestCase):

    def test_command_group_timeout_and_output_failures_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_bounded([sys.executable, '-c', 'import time;time.sleep(30)'], cwd=Path(tmp), timeout=0.1)
            self.assertEqual(result['error'], 'command_timeout')
            self.assertLess(result['duration_seconds'], 3)
            result = run_bounded([sys.executable, '-c', 'print("x"*1000001)'], cwd=Path(tmp), timeout=2)
            self.assertEqual(result['error'], 'output_too_large')

    def test_verifier_preserves_prior_success_and_sanitizes_failure_evidence(self):
        verify = runpy.run_path(str(ROOT / 'scripts/verify_labs.py'))['verify']
        for fault in ['timeout', 'malformed', 'nonzero']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                count = [0]

                def runner(command, **kw):
                    count[0] += 1
                    if count[0] == 1:
                        return run_bounded(command, **kw)
                    if count[0] == 2:
                        if fault == 'timeout':
                            return run_bounded([sys.executable, '-c', 'import time;time.sleep(30)'], cwd=ROOT, timeout=0.1)
                        return {'exit_code': 0 if fault == 'malformed' else 17, 'error': None, 'stdout': 'SECRET_CANARY /private/PATH_CANARY', 'duration_seconds': 0.01}
                    return {'exit_code': 17, 'error': None, 'stdout': 'SECRET_CANARY', 'duration_seconds': 0.01}
                path = Path(tmp) / 'report.json'
                report = verify(path, runner=runner)
                self.assertFalse(report['all_passed'])
                self.assertTrue(report['results'][0]['passed'])
                self.assertEqual(report['commands_run'], 14)
                self.assertEqual(report['results'][1]['stage'], 'baseline')
                raw = path.read_text()
                self.assertNotIn('SECRET_CANARY', raw)
                self.assertNotIn('/private/PATH_CANARY', raw)
                self.assertEqual(json.loads(raw)['status'], 'completed')
