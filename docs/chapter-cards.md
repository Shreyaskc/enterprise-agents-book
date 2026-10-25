# Twelve chapter cards

Start at [Build start](build-start.md). Run from the lab root with an installed interpreter. Each independent card starts in a fresh source extraction and default policy v3; only Chapter 6 deliberately shares one workflow database across two commands. Never delete an existing database to repeat a card: choose a new extraction, state filename or run ID. Outputs below are expected checks, not a claim that your run has already happened.

All concept tracks need reading only; all build tracks use standard-library Python and synthetic fixtures. Enterprise-design prompts are recommendations and unimplemented production extensions unless a test is explicitly named. Book and diagram build sources are private and are not supplied here.

## Chapter 1: Fundamentals

Learn the vocabulary and choose a depth track.

**Prerequisites:** None for concept; shell basics to run. **Owner:** Product lead and all readers. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents glossary
python -m unittest -v tests.test_core.CoreTests.test_documents_cannot_execute_instructions
```

**Expected:** Definitions distinguish fixed workflow transitions from planner-selected actions; all three learning tracks appear.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 2: Data and baseline

Separate transaction evidence from customer reports and operational truth.

**Prerequisites:** Basic Python, dictionaries, integer money. **Owner:** Application engineer and data steward. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents baseline
python -m unittest -v tests.test_core.CoreTests.test_fixture_hash_is_verified
```

**Expected:** CASE-SYN-104 references INV-SYN-4817: quantity 2, GBP 12.50 each, total GBP 25.00. The report of one red mug is not proof of fulfillment; delivery is unknown and refund authorization is false.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 3: Retrieval with provenance

Retrieve permitted evidence while preserving provenance.

**Prerequisites:** Lab 2, text matching, source attribution. **Owner:** Retrieval engineer and data steward. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents retrieve --query "returns purchase case"
python -m unittest -v tests.test_core.CoreTests.test_unknown_retrieval_abstains
```

**Expected:** One returns-v3 evidence hit with source synthetic://northstar/returns/v3, version v3, score 3, span [0,188] and SHA-256 f54083a5fda8da6cf0fe25ba22fa098446dcecd67467a407ba7900ed47d4a797.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 4: Bounded tool agent

A planner proposes; the application bounds and validates tools.

**Prerequisites:** Labs 2–3, functions, JSON, runtime validation. **Owner:** Application engineer. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents agent
python -m northstar_agents agent --maximum-steps 2
```

**Expected:** Three deterministic read tools in case/invoice/policy order. It is a rule simulation; delivery stays unknown and refund authorization false.

**Negative trial:** the two-step budget exits 2 with structured code `budget_exhausted` on stderr and no traceback. Partial tool reads do not create a case.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 5: Memory lifecycle

Memory needs purpose, scope, freshness and deletion.

**Prerequisites:** Lab 4, state and expiry. **Owner:** Application engineer and privacy owner. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents memory
python -m unittest -v tests.test_core.CoreTests.test_memory_ttl_source_version_scope_and_delete
```

**Expected:** Stale v3 note is not disclosed as v4. A new branch-only v4 note is fresh. Harbor sees missing, deletion returns missing, canonical policy remains v3.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 6: Durability and recovery

A checkpoint resumes reads; an outbox records intent and reconciles a separate local destination.

**Prerequisites:** Labs 4–5, SQL transactions and state machines. **Owner:** Backend engineer and SRE. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06 --pause-after purchase_checked
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06
python -m northstar_agents durability-lab --report artifacts/reports/durability-lab.json
```

**Expected:** First process pauses at purchase_checked/version 1. Second process reaches completed/version 3 and resumed true; reviewer approval is still required. The separate durability command reports six scenarios, acknowledged reopened source state and matching destination receipts.

**Implemented recovery:** [two-process pause/resume](reliability-lab.md#read-only-workflow) and the separate two-store lab retain the difference between resume and receipt reconciliation. [Receipt boundary tests](../tests/test_round1_recovery.py) cover expiry, revocation, full receipt identity and explicit reauthorization.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 7: Approvals and security

Approval binds an exact action and current authorization governs effects.

**Prerequisites:** Lab 6, authorization and transactional boundaries. **Owner:** Application, security and business approval owners. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents approvals
python -m unittest -v tests.test_core.CoreTests.test_approval_binds_exact_payload_and_policy
```

**Expected:** Exactly one local case. Same request replay returns the same ID, replayed true, local_mutations 1. The reviewer is a synthetic role; no refund occurs.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 8: Evaluation and observability

Evaluation is an executable contract; envelopes alone do not establish correctness.

**Prerequisites:** Labs 2–7, test assertions and measurement. **Owner:** Quality owner and SRE. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents evaluate --output artifacts/reports/evaluation.json
python -m unittest -v tests.test_cli.LabAcceptanceTests.test_report_is_written_and_existing_user_file_preserved
```

**Expected:** 13 distinct regression cases in the required order; each expected value equals its observed result and all pass. Source and fixture hashes identify what was executed. No model quality is measured.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 9: Specialist teams

Routing and handoff do not merge role privileges.

**Prerequisites:** Labs 4 and 7–8, role boundaries and routing. **Owner:** Service and Inventory Operations engineers. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents teams
python -m unittest -v tests.test_core.CoreTests.test_team_permissions_are_distinct_inside_one_tenant
```

**Expected:** Service investigation and Inventory sales signal stay within distinct team permissions inside Northstar. Synthetic units sold is 5; stock is unknown and purchase authorization is false.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 10: Shared platform architecture

Tenancy is an application boundary, not a prompt instruction.

**Prerequisites:** Labs 6–9, tenancy and least privilege. **Owner:** Platform Engineering and security. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents platform
python -m unittest -v tests.test_core.CoreTests.test_tenant_invoice_and_case_leakage_denied
```

**Expected:** Northstar teams and Harbor isolation tenant are named. All four cross-tenant/role denial checks are true.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 11: Deployment and operations

Backups, revocation and recovery need runbooks and actual checks.

**Prerequisites:** Lab 10, backup, incident and change management. **Owner:** Platform Engineering and SRE. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents operations
python -m unittest -v tests.test_core.CoreTests.test_backup_restore_preserves_checkpoint_receipt_and_revocation
```

**Expected:** Fresh store counts are zero; deployment status is local_teaching_store_not_distributed_service. Backup/revocation selector verifies recovery boundaries.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.

## Chapter 12: Capstone

Combine the implemented components without claiming enterprise readiness.

**Prerequisites:** Labs 1–11. **Owner:** Cross-functional delivery team. **Depth:** understand the concept; build the local example; design for enterprise deployment.

```sh
python -m northstar_agents capstone --report artifacts/reports/capstone.json
python -m unittest -v tests.test_core.CoreTests.test_timeout_after_commit_reconciles_without_second_mutation
```

**Expected:** Completed read-only workflow and one approved local case with ID. All 13 regressions pass, delivery is unknown, Inventory cannot purchase, production_ready is false.

**Implemented check:** the standalone selector above should report exactly one test, no failures/errors/skips, and `OK` on stderr. This is an actual named regression, not a hypothetical exercise.

**Repeat safely:** use fresh state/report paths. **Enterprise extension:** adapt authentication, policies, services and operations under your organization’s design review; this local lab supplies no SSO, production human-review interface, gateway, distributed fencing, deployment validation or ROI measurement.
