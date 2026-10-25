# Approval-bound note, outbox and separate simulated destination

This is a separate Lab 6 exercise. Keep `workflow` for read-only checkpoint pause/resume and `approvals` for local case creation. The reliability command connects an approved synthetic note to a transactional outbox and a second local destination:

```sh
python -m northstar_agents durability-lab --report artifacts/reports/durability-lab.json
```

Use a fresh report filename on repeat runs. The command creates isolated temporary source/destination databases for each scenario, performs no network/model requests, then deletes those lab files. The report retains observed intermediate/final counts and receipts. No real case system or customer is contacted.

The exact note concerns `CASE-SYN-104` / `INV-SYN-4817`: two blue mugs ordered at GBP 12.50 each, one red mug reported, fulfillment unknown. The synthetic reviewer role approves the canonical note payload. That demonstrates the gate mechanics; it is not a real human review.

## Boundaries implemented

1. `CaseNote` strictly validates its schema and binds the exact note, case, invoice, policy version, tenant and proposing principal into the request digest.
2. One **source SQLite transaction** checks current permissions, purchase/case/policy and approval scope/expiry, then persists note intent and outbox row while consuming that approval. A failure before commit rolls all three changes back.
3. Dispatch commits its local attempt count, releases the source transaction, and calls a **different SQLite database**. No transaction spans both stores.
4. The simulated receiver atomically persists its case note and receipt under a tenant-scoped idempotency key. Matching key/digest replays a receipt; conflicting payload reuse is rejected. The receiver independently recomputes the envelope digest.
5. The source records an acknowledgement only after observing a matching receipt. An ambiguous acknowledgement leaves the source pending. Reconciliation reads the destination ledger by key and digest before updating local state; if no receipt exists, an explicit retry can use the same key.
6. Before dispatch can create a new effect, current creator permissions, reviewer authority, exact grant scope/expiry and policy are checked again. Historical receipt reconciliation instead requires current owner `case.read` authority and verification of the immutable intent and matching destination receipt; it does not authorize a new effect or renew approval. Tenant predicates scope the source outbox and destination receipt lookup.

## Six observed scenarios

| Injected scenario | Expected intermediate state | Recovery checked |
| --- | --- | --- |
| Before source intent commit | No intent, outbox or destination note; approval not consumed | Re-enqueue under the still-valid approval, then dispatch |
| Before destination commit | Source intent/outbox pending; destination has no note/receipt | Observe no destination receipt, then explicitly retry |
| Timeout after destination commit | Source remains pending; destination has one note/receipt | Reconcile the receipt; no second effect |
| Response observed, crash before local receipt | Source remains pending; destination has one note/receipt | Reconcile the receipt; subsequent dispatch returns local acknowledgement |
| Two duplicate dispatchers | Both reach a bounded barrier before destination transactions | One destination insert and one replay; one note under the key |
| Reuse key with different note | Existing note remains | Reject the conflict in both source and destination |

The test suite also reconciles a committed destination timeout from a new Python process, verifies approval payload binding and revocation, and checks tenant-scoped lookup. The command report contains actual expected/observed values; it does not substitute expected output for an executed run.

## Exact guarantee tested

The observed local tests demonstrate source transaction atomicity and one simulated destination note per tenant/key with a matching digest under the tested retries and bounded two-dispatcher race. They show recovery from injected lost acknowledgements. They do **not** establish distributed exactly-once execution, arbitrary network-partition tolerance, power-loss durability under every configuration, authenticated receiver transport, multi-node fencing, production migration behavior or a real third-party idempotency contract.

The destination is trusted local code. A production design still needs authenticated worker/receiver identity, independently protected databases, queue/lease and reconciliation ownership, budgets, backup/migration validation and deployment-specific failure tests. No hidden model reasoning is involved or recorded.

## Read-only workflow

Chapter 6 starts with two separate Python invocations. Choose a new database path if this one already exists:

```sh
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06 --pause-after purchase_checked
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06
python -m northstar_agents trace --db .state/workflow.sqlite
```

The completed checkpoint is a historical read with a current `case.read` check. `result_kind`, `policy_current` and `fresh_action_authorization_required` make its limits explicit. Removing a tool permission does not turn historical evidence into permission to run that tool; proposals and new effects still require fresh validation.

## Receipt recovery and authorization

Dispatch is a potential new effect: it requires current proposer permissions, current policy, an unexpired exact-payload grant and a currently authorized reviewer. Reconciliation reads the simulated destination ledger and records only an already committed effect. It requires current owner case-read authority and immutable intent integrity. Expired approval, reviewer revocation or changed policy does not erase a historical receipt or permit another effect. Revoked readers are denied; an authorized operator must review access through the trusted identity administration boundary before recovery. This lab supplies no override or human administration UI.

Receipts bind tenant, request key, payload digest, deterministic note ID and stored status; the receiver’s matching durable note and receipt must exist. Receipt A cannot acknowledge B even when both payloads are identical. These checks trust a second local database, not a production receiver identity.

After `no_destination_receipt`, never infer rollback from an ambiguous network situation in a real system. In this local demonstration a fresh grant may be explicitly bound to the same immutable key/payload through `reauthorize(ctx, key, approval_id)`, consuming it once. If policy changed or authority was revoked, the response directs an authorized manual review: no automatic dispatch occurs. A changed note needs a new approved intent and key under the applicable policy; the lab does not migrate or rewrite the old intent.

The six command scenarios now check reopened source state `acknowledged`, matching destination receipts and consumed approval as well as row counts. Duplicate dispatch remains a bounded two-thread/local-SQLite observation. No distributed exactly-once guarantee is claimed.
