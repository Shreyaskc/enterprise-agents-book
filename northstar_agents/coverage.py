# SPDX-License-Identifier: MIT
"""Versioned nonempty coverage contracts, checked before any scenario is executed."""
import json
import shlex
from .contracts import Rejected
REGRESSION_IDS = ('purchase_baseline', 'retrieval_provenance', 'bounded_agent', 'tenant_isolation', 'document_injection', 'approval_binding', 'permission_revocation', 'duplicate_request', 'timeout_after_commit', 'crash_recovery', 'stale_memory', 'budget_exhaustion', 'team_permissions')
LAB_STAGES = ('glossary', 'baseline', 'retrieve', 'agent', 'memory', 'workflow', 'approvals', 'evaluate', 'teams', 'platform', 'operations', 'capstone')

def load_contract(path, kind):
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise Rejected('invalid_coverage_contract') from exc
    field = 'cases' if kind == 'regression' else 'labs'
    if type(data) is not dict or set(data) != {'schema_version', 'contract_kind', field} or data['schema_version'] != 1 or (type(data['schema_version']) is not int) or (data['contract_kind'] != kind):
        raise Rejected('invalid_coverage_contract')
    rows = data[field]
    if type(rows) is not list or not rows:
        raise Rejected('invalid_coverage_contract')
    if kind == 'regression':
        if any((type(c) is not dict or set(c) != {'id', 'expected'} or type(c['expected']) is not dict for c in rows)):
            raise Rejected('invalid_coverage_contract')
        if [c['id'] for c in rows] != list(REGRESSION_IDS):
            raise Rejected('invalid_coverage_contract')
    else:
        if len(rows) != 12:
            raise Rejected('invalid_coverage_contract')
        for i, (row, stage) in enumerate(zip(rows, LAB_STAGES), 1):
            required = {'lab', 'title', 'stage', 'command', 'prerequisites', 'owner'} | ({'resume_command', 'reliability_command'} if i == 6 else set())
            if type(row) is not dict or set(row) != required or row['lab'] != i or (type(row['lab']) is not int) or (row['stage'] != stage):
                raise Rejected('invalid_coverage_contract')
            for key in ('command', 'resume_command', 'reliability_command'):
                if key not in row:
                    continue
                if type(row[key]) is not str:
                    raise Rejected('invalid_coverage_contract')
                try:
                    tokens = shlex.split(row[key])
                except ValueError as exc:
                    raise Rejected('invalid_coverage_contract') from exc
                expected_stage = 'durability-lab' if key == 'reliability_command' else stage
                if tokens[:4] != ['python', '-m', 'northstar_agents', expected_stage]:
                    raise Rejected('invalid_coverage_contract')
                if i == 6 and key == 'command' and (tokens[-2:] != ['--pause-after', 'purchase_checked']):
                    raise Rejected('invalid_coverage_contract')
                if i == 6 and key == 'resume_command' and ('--pause-after' in tokens):
                    raise Rejected('invalid_coverage_contract')
    return rows
