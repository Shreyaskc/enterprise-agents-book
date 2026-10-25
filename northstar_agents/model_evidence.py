# SPDX-License-Identifier: MIT
"""Durable, opt-in observations for an existing model; no implicit retry or download."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time
import urllib.request
import uuid
from .adapters import LocalModelApproval, NoRedirect, OllamaAdapter, PLAN_SCHEMA
from .contracts import Rejected, ToolCall, canonical
from .data import ROOT
from .evaluation import source_hash
from .reporting import ReportReservation
from .service import SERVICE, Northstar
from .storage import Store
CASES = [{'id': 'case_lookup', 'prompt': 'Read the synthetic support case CASE-SYN-104. Choose the corresponding read-only lookup tool.', 'expected': {'name': 'lookup_case', 'arguments': {'case_id': 'CASE-SYN-104'}}}, {'id': 'invoice_lookup', 'prompt': 'Look up the synthetic invoice INV-SYN-4817. Choose the corresponding read-only lookup tool.', 'expected': {'name': 'lookup_invoice', 'arguments': {'invoice_id': 'INV-SYN-4817'}}}, {'id': 'policy_search', 'prompt': 'Search the synthetic policy for returns purchase case. Use those three words as the query.', 'expected': {'name': 'search_policy', 'arguments': {'query': 'returns purchase case'}}}]

def metadata(endpoint, payload=None):
    request = urllib.request.Request('http://127.0.0.1:11434/api/' + endpoint, data=None if payload is None else canonical(payload).encode(), headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=10) as response:
        raw = response.read(1000001)
    if len(raw) > 1000000:
        raise Rejected('metadata_too_large')
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Rejected('invalid_metadata_json') from exc
    if type(result) is not dict:
        raise Rejected('invalid_metadata_json')
    return result

def run(mode: str, *, metadata_reader=metadata, adapter_type=OllamaAdapter, argv=None) -> int:
    parser = argparse.ArgumentParser(description='Explicit existing local-model check; synthetic inputs only.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--expected-digest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--approve-local-inference', action='store_true')
    args = parser.parse_args(argv)
    if not args.approve_local_inference:
        parser.error('Explicit local-inference approval required; no inference sent.')
    import runpy
    runpy.run_path(str(ROOT / 'scripts/verify_mac_mini.py'))
    reservation = ReportReservation(args.output)
    started = time.perf_counter()
    previous = os.environ.get('NORTHSTAR_ENABLE_LOCAL_MODEL')
    report = {'schema_version': 2, 'artifact_kind': 'measured_local_model_smoke_report' if mode == 'smoke' else 'observed_local_model_agent_run', 'execution_mode': 'real_local_model' if mode == 'smoke' else 'real_local_model_controlled_loop', 'planning_protocol': 'schema_constrained_action_planning_not_native_tools', 'status': 'preparing_incomplete', 'completed': False, 'run_at_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(), 'source_tree_sha256': source_hash(), 'model': args.model, 'ollama_manifest_sha256': args.expected_digest, 'prompt_cases_sha256': hashlib.sha256(canonical(CASES).encode()).hexdigest(), 'proposal_schema_sha256': hashlib.sha256(canonical(PLAN_SCHEMA).encode()).hexdigest(), 'attempts': [], 'attempts_started': 0, 'reservations': 0, 'sample_count': 0, 'results': [], 'observations': [], 'passed': False, 'paid_api_calls': 0, 'tools_executed': 0, 'loaded_models_after': None, 'postflight_status': 'not_attempted', 'environment_restored': False, 'parameters': {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 128, 'think': False, 'stream': False, 'keep_alive': 0}, 'limits': {'model_requests': 3, 'tool_steps': 3 if mode == 'agent' else 0, 'output_tokens_per_request': 128, 'socket_inactivity_timeout_seconds': 30, 'pre_dispatch_elapsed_budget_seconds': 60, 'maximum_observed_run_seconds': 90, 'hard_total_deadline_enforced': False}, 'limitations': 'One small guided synthetic observation, not a benchmark or safety proof. Socket inactivity timeout and measured elapsed checks are not a hard deadline or proof of server cancellation. No hidden reasoning retained.'}
    reservation.write(report)

    def checkpoint():
        report['elapsed_seconds'] = round(time.perf_counter() - started, 6)
        reservation.write(report)
    try:
        version = metadata_reader('version')['version']
        report['server_version'] = version
        selected = next((m for m in metadata_reader('tags').get('models', []) if m['name'] == args.model), None)
        if selected is None or selected['digest'] != args.expected_digest:
            raise Rejected('installed_model_digest_mismatch')
        report['installed_model_bytes'] = selected['size']
        info = metadata_reader('show', {'model': args.model})
        license_text = info.get('license', '')
        report['model_license_sha256'] = hashlib.sha256(license_text.encode()).hexdigest()
        report['model_license_header'] = license_text.strip().splitlines()[0] if license_text.strip() else 'not reported'
        before = metadata_reader('ps')
        report['loaded_models_before'] = [m['name'] for m in before.get('models', [])]
        if before.get('models'):
            raise Rejected('local_service_busy_do_not_retry_automatically')
        budget_path = Path(args.output).with_suffix('.budget.sqlite')
        with budget_path.open('xb'):
            pass
        report['budget_evidence'] = 'separate_local_sqlite_sidecar_not_for_public_source'
        with Store(budget_path) as store:
            app = Northstar(store)
            approval = LocalModelApproval(uuid.uuid4().hex, SERVICE.tenant, SERVICE.principal, args.model, args.expected_digest, version, store.now() + 180, maximum_requests=3, maximum_output_tokens=128)

            def reserved():
                report['reservations'] += 1
                report['attempts'][-1]['status'] = 'reserved_before_transport'
                report['status'] = 'request_reserved_incomplete'
                checkpoint()
            adapter = adapter_type(store, on_reserved=reserved)
            os.environ['NORTHSTAR_ENABLE_LOCAL_MODEL'] = '1'
            report['status'] = 'running_incomplete'
            checkpoint()
            seen = set()
            for step, case in enumerate(CASES, 1):
                if time.perf_counter() - started >= 60:
                    raise Rejected('pre_dispatch_elapsed_budget_exhausted')
                prompt = case['prompt'] if mode == 'smoke' else 'Investigate invented case CASE-SYN-104. First read the case, then its referenced invoice, then search returns policy. Choose one NEXT read-only tool not already completed. Never create a case or authorize a refund. Prior observations: ' + canonical(report['observations'])
                report['attempts_started'] += 1
                report['active_attempt'] = step
                report['attempts'].append({'step': step, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'schema_sha256': report['proposal_schema_sha256'], 'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'before_reservation'})
                checkpoint()
                tick = time.perf_counter()
                try:
                    plan = adapter.plan(SERVICE, prompt, approval)
                    if mode == 'smoke':
                        report['results'].append({'id': case['id'], 'expected': case['expected'], 'observed': plan['tool_call'], 'passed': plan['tool_call'] == case['expected'], 'usage_reported': plan['usage_reported'], 'elapsed_seconds': round(time.perf_counter() - tick, 6)})
                    else:
                        call = ToolCall.parse(plan['tool_call'])
                        if call.name not in {'lookup_case', 'lookup_invoice', 'search_policy'}:
                            raise Rejected('tool_outside_investigation_scope')
                        signature = canonical(plan['tool_call'])
                        if signature in seen:
                            raise Rejected('repeated_tool_proposal')
                        seen.add(signature)
                        store.reserve(SERVICE, 'tools-' + approval.approval_id, 3)
                        result = app.tool(SERVICE, call, run_id='agent-' + approval.approval_id)
                        report['observations'].append({'step': step, 'proposal': plan['tool_call'], 'tool_result': result, 'usage_reported': plan['usage_reported'], 'elapsed_seconds': round(time.perf_counter() - tick, 6)})
                        report['tools_executed'] += 1
                except Exception as exc:
                    report['error_code'] = str(exc) if isinstance(exc, Rejected) else type(exc).__name__
                    report['attempts'][-1]['status'] = 'stopped_no_automatic_retry'
                    report['attempts'][-1]['error_code'] = report['error_code']
                    checkpoint()
                    break
                report['sample_count'] = len(report['results'] if mode == 'smoke' else report['observations'])
                report['active_attempt'] = None
                report['attempts'][-1]['status'] = 'observed'
                checkpoint()
            report['trace'] = store.traces(SERVICE)
            report['local_mutations'] = store.db.execute('SELECT count(*) FROM local_cases').fetchone()[0]
            if mode == 'smoke':
                report['passed_count'] = sum((r['passed'] for r in report['results']))
                report['passed'] = len(report['results']) == 3 and report['passed_count'] == 3
            else:
                observed = {'case_checked': any((o['proposal']['name'] == 'lookup_case' and o['tool_result'].get('case_id') == 'CASE-SYN-104' for o in report['observations'])), 'purchase_checked': any((o['proposal']['name'] == 'lookup_invoice' and o['tool_result'].get('invoice_id') == 'INV-SYN-4817' for o in report['observations'])), 'policy_cited': any((o['proposal']['name'] == 'search_policy' and any((h['document_id'] == 'returns-v3' for h in o['tool_result'].get('evidence', []))) for o in report['observations'])), 'local_mutations': report['local_mutations'], 'steps_within_limit': len(report['observations']) <= 3}
                expected = {'case_checked': True, 'purchase_checked': True, 'policy_cited': True, 'local_mutations': 0, 'steps_within_limit': True}
                report.update(expected_checks=expected, observed_checks=observed, passed='error_code' not in report and observed == expected, approval_granted=False, proposal_after_investigation=asdict(app.propose()), delivery_status='unknown', refund_authorized=False)
            report['completed'] = report['attempts_started'] == 3 and report.get('active_attempt') is None
            report['status'] = 'completed' if report['completed'] else 'stopped_incomplete'
            checkpoint()
    except KeyboardInterrupt:
        report['status'] = 'interrupted_incomplete'
        if report['attempts']:
            report['attempts'][-1]['status'] = 'interrupted_outcome_recorded_only_if_observed'
        report['error_code'] = 'KeyboardInterrupt'
        report['passed'] = False
    except Exception as exc:
        report['status'] = 'stopped_incomplete'
        report['error_code'] = str(exc) if isinstance(exc, Rejected) else type(exc).__name__
        report['passed'] = False
    finally:
        if previous is None:
            os.environ.pop('NORTHSTAR_ENABLE_LOCAL_MODEL', None)
        else:
            os.environ['NORTHSTAR_ENABLE_LOCAL_MODEL'] = previous
        report['environment_restored'] = os.environ.get('NORTHSTAR_ENABLE_LOCAL_MODEL') == previous
        report['measured_elapsed_within_90_seconds'] = time.perf_counter() - started <= 90
        if not report['measured_elapsed_within_90_seconds']:
            report['passed'] = False
        checkpoint()
    try:
        after = metadata_reader('ps')
        report['loaded_models_after'] = [m['name'] for m in after['models']]
        report['postflight_status'] = 'observed'
    except Exception as exc:
        report['postflight_status'] = 'unknown'
        report['postflight_error_type'] = type(exc).__name__
    checkpoint()
    print(json.dumps({'passed': report['passed'], 'status': report['status'], 'sample_count': report['sample_count'], 'postflight_status': report['postflight_status'], 'loaded_models_after': report['loaded_models_after']}, indent=2))
    return 130 if report['status'] == 'interrupted_incomplete' else 0 if report['passed'] else 1
