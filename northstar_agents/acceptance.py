# SPDX-License-Identifier: MIT
"""Semantic acceptance v1, beyond envelopes and exit status."""
import hashlib
from .coverage import REGRESSION_IDS
POLICY_SHA = 'f54083a5fda8da6cf0fe25ba22fa098446dcecd67467a407ba7900ed47d4a797'

def regression(o):
    return o.get('all_passed') is True and o.get('sample_count') == 13 and (o.get('passed_count') == 13) and ([r['id'] for r in o['results']] == list(REGRESSION_IDS)) and all((r['passed'] is True and r['expected'] == r['observed'] for r in o['results']))

def retrieval(o):
    h = o['evidence']
    return o['method'] == 'lexical_overlap_not_embeddings' and o['status'] == 'supported' and (len(h) == 1) and all((x['document_id'] == 'returns-v3' and x['version'] == 'v3' and (x['source'] == 'synthetic://northstar/returns/v3') and (x['sha256'] == POLICY_SHA == hashlib.sha256(x['quote'].encode()).hexdigest()) and (x['span'] == [0, len(x['quote'])] == [0, 188]) and (x['score'] == 3) and (x['source_kind'] == 'invented_teaching_material') for x in h))

def agent(o):
    r = o['results']
    return o['planner'] == 'deterministic_rule_simulation' and o['steps'] == 3 and (len(r) == 3) and ([x['tool'] for x in r] == ['lookup_case', 'lookup_invoice', 'search_policy']) and (r[0]['result']['case_id'] == 'CASE-SYN-104') and (r[1]['result']['invoice_id'] == 'INV-SYN-4817') and (r[1]['result']['quantity'] == 2) and (r[1]['result']['unit_price_pence'] == 1250) and retrieval(r[2]['result']) and (o['delivery_status'] == 'unknown') and (o['refund_authorized'] is False)

def platform(o):
    return o['northstar_teams'] == ['service_operations', 'inventory_operations', 'platform_engineering'] and o['isolation_tenant'] == 'harbor' and all((o[k] is True for k in ['cross_tenant_invoice_denied', 'service_to_inventory_denied', 'inventory_to_service_denied', 'platform_business_data_denied']))

def inventory(o):
    return o['stock_code'] == 'MUG-BLUE-SYN' and o['synthetic_units_sold'] == 5 and (o['inventory_on_hand'] == 'unknown') and (o['replenishment_quantity'] == 'not_determined') and (o['purchase_authorized'] is False)

def durability(o):
    names = ['before_intent_commit', 'before_destination_commit', 'timeout_after_destination_commit', 'after_response_before_receipt', 'concurrent_duplicate_dispatch', 'conflicting_key_reuse']
    if o['scenario_count'] != 6 or o['all_passed'] is not True or [r['scenario'] for r in o['results']] != names:
        return False
    for r in o['results'][:4]:
        if not (r['fault_observed'] is True and r['expected_intermediate'] == r['observed_intermediate'] and (r['passed'] is True) and (r['observed_final'] == r['expected_final'] == {'source_intents': 1, 'source_outbox': 1, 'destination_notes': 1, 'source_state': 'acknowledged', 'receipt_matches_destination': True, 'approval_consumed': 1}) and (r['recovery']['status'] == 'acknowledged')):
            return False
    return o['results'][4]['destination_replay_flags'] == [False, True] and o['results'][4]['observed']['destination_notes'] == 1 and (o['results'][4]['passed'] is True) and (o['results'][5]['source_rejected'] is True) and (o['results'][5]['destination_rejected'] is True) and (o['results'][5]['passed'] is True)

def semantic_checks(stage, o, *, resumed=False):
    try:
        common = type(o) is dict and o.get('schema_version') == 1 and (o.get('model_calls') == 0) and (o.get('execution_mode') == 'deterministic_simulation')
        if stage == 'evaluate':
            return common and regression(o)
        if not common or o.get('stage') != stage or o.get('fixture_kind') != 'invented_teaching_material_not_uci':
            return False
        if stage == 'glossary':
            return len(o['tracks']) == 3 and all((type(o[k]) is str and o[k] for k in ['workflow', 'agent', 'tool', 'retrieval', 'memory', 'routing', 'handoff', 'multi_agent']))
        if stage == 'baseline':
            return o['case_id'] == 'CASE-SYN-104' and o['invoice_id'] == 'INV-SYN-4817' and (o['ordered'] == {'description': 'blue mug', 'quantity': 2, 'unit_price_gbp': '12.50'}) and (o['invoice_total_gbp'] == '25.00') and (o['delivery_status'] == 'unknown') and (o['refund_authorized'] is False) and ('red mug' in o['customer_report'])
        if stage == 'retrieve':
            return retrieval(o)
        if stage == 'agent':
            return agent(o)
        if stage == 'memory':
            return o['stale'] == {'status': 'stale'} and o['fresh'] == {'status': 'fresh', 'value': 'Branch-only synthetic policy v4 summary'} and (o['harbor_view'] == {'status': 'missing'}) and (o['after_deletion'] == {'status': 'missing'}) and (o['branch_policy_version'] == 'v4') and (o['canonical_policy_version'] == 'v3')
        if stage == 'workflow':
            if resumed:
                return o['state']['stage'] == 'completed' and o['checkpoint_version'] == 3 and (o['resumed'] is True) and (o['state']['requires_reviewer_approval'] is True) and (o['fresh_action_authorization_required'] is True)
            return o['state'] == {'stage': 'purchase_checked', 'case_id': 'CASE-SYN-104'} and o['checkpoint_version'] == 1 and (o['paused'] is True)
        if stage == 'durability-lab':
            return durability(o)
        if stage == 'approvals':
            return o['first']['status'] == 'created_locally' and o['first']['replayed'] is False and (o['repeat']['replayed'] is True) and (o['first']['local_case_id'] == o['repeat']['local_case_id']) and (o['local_mutations'] == 1) and (o['refund_authorized'] is False) and (o['reviewer'] == 'synthetic_reviewer_role_not_a_real_human_review') and (o['proposal']['policy_version'] == 'v3')
        if stage == 'teams':
            return o['tenant'] == 'northstar' and o['router'] == 'deterministic_rule_simulation' and agent(o['service_operations']) and inventory(o['inventory_operations'])
        if stage == 'platform':
            return platform(o)
        if stage == 'operations':
            return o['tenant'] == 'northstar' and o['local_case_count'] == 0 and (o['checkpoint_count'] == 0) and (o['expired_approval_count'] == 0) and (o['deployment_status'] == 'local_teaching_store_not_distributed_service')
        if stage == 'capstone':
            return agent(o['investigation']) and o['workflow']['state']['stage'] == 'completed' and (o['workflow']['state']['requires_reviewer_approval'] is True) and (o['local_action']['status'] == 'created_locally') and bool(o['local_action']['local_case_id']) and inventory(o['inventory_signal']) and platform(o['isolation']) and regression(o['regression']) and (o['production_ready'] is False) and (not any(('reasoning' in str(e).lower() for e in o['trace'])))
        return False
    except (KeyError, TypeError, ValueError, IndexError):
        return False
