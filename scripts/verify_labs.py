# SPDX-License-Identifier: MIT
"""Validated nonempty chapter contract, bounded children and durable semantic evidence."""
import argparse
from datetime import datetime, timezone
import hashlib, json, os, platform, runpy, shlex, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from northstar_agents.acceptance import semantic_checks
from northstar_agents.contracts import Rejected
from northstar_agents.coverage import load_contract
from northstar_agents.evaluation import source_hash
from northstar_agents.execution import run_bounded
from northstar_agents.reporting import ReportReservation

def verify(report_path, *, runner=run_bounded, contract_path=None, timeout=60):
    reservation = ReportReservation(report_path)
    path = contract_path or ROOT / 'docs/lab-index.json'
    report = {'schema_version': 2, 'artifact_kind': 'observed_lab_acceptance_report', 'acceptance_semantics_version': 1, 'lab_contract_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None, 'python': platform.python_version(), 'run_at_utc': datetime.now(timezone.utc).isoformat(), 'source_tree_sha256': source_hash(), 'status': 'running_incomplete', 'all_passed': False, 'commands_run': 0, 'results': []}
    reservation.write(report)
    try:
        labs = load_contract(path, 'labs')
    except Rejected as exc:
        report.update(status='invalid_contract', error_code=str(exc))
        reservation.write(report)
        return report
    with tempfile.TemporaryDirectory(prefix='northstar-labs-') as tmp:
        for lab in labs:
            for key in ['command', 'resume_command', 'reliability_command']:
                if key not in lab:
                    continue
                tokens = shlex.split(lab[key])[3:]
                for option in ['--db', '--output', '--report']:
                    if option in tokens:
                        index = tokens.index(option) + 1
                        tokens[index] = str(Path(tmp) / Path(tokens[index]).name)
                stage = 'durability-lab' if key == 'reliability_command' else lab['stage']
                command = [sys.executable, 'scripts/run_offline.py', *tokens]
                env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
                try:
                    run = runner(command, cwd=ROOT, timeout=timeout, env=env)
                except Exception as exc:
                    run = {'exit_code': None, 'error': 'runner_failure_' + type(exc).__name__, 'stdout': '', 'duration_seconds': None}
                error = run['error']
                output = None
                if not error:
                    if run['exit_code'] != 0:
                        error = 'nonzero_exit'
                    else:
                        try:
                            output = json.loads(run['stdout'])
                            if type(output) is not dict:
                                raise ValueError
                        except (ValueError, TypeError):
                            error = 'malformed_json_output'
                passed = error is None and semantic_checks(stage, output, resumed=key == 'resume_command')
                report['results'].append({'lab': lab['lab'], 'stage': stage, 'lab_command': lab[key], 'command_key': key, 'exit_code': run['exit_code'], 'duration_seconds': run['duration_seconds'], 'error_code': error if error else None if passed else 'semantic_acceptance_failed', 'passed': passed, 'semantic_checks_version': 1, 'observed_output': output if passed else None})
                report['commands_run'] += 1
                reservation.write(report)
    report['all_passed'] = len(report['results']) == 14 and all((r['passed'] for r in report['results']))
    report['status'] = 'completed'
    reservation.write(report)
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    runpy.run_path(str(ROOT / 'scripts/verify_mac_mini.py'))
    report = verify(args.report)
    print(json.dumps({'commands_run': report['commands_run'], 'all_passed': report['all_passed'], 'status': report['status']}, indent=2))
    return 0 if report['all_passed'] else 1
if __name__ == '__main__':
    raise SystemExit(main())
