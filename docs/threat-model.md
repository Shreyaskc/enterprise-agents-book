# Threat model for the teaching implementation

Assets are tenant business records, approval authority, retained memory, workflow state, local effect receipts, budgets and trace exports. Untrusted inputs include user questions, document text, tool JSON, model proposals, source workbooks and retry requests. The Python process, fixture identity injection and local database file owner are trusted in this example.

| Threat | Implemented control | Evidence | Residual risk / recommended enterprise work |
| --- | --- | --- | --- |
| Forged tenant or tool authority | Separate Context; exact tool argument fields; current permission lookup | Strict parser, tenant and team tests | Authenticate the context at a real gateway; isolate database credentials and runtime |
| Cross-tenant data/trace access | Tenant-scoped records, composite keys, scoped trace queries | Canary, memory, checkpoint, approval and trace tests | Application checks do not protect against direct file access; design database/runtime boundaries |
| Document injection | Documents are data; fixed planner; narrow sample filter | Injected-document and no-mutation tests | Detector is not comprehensive; evaluate model-influenced control and exfiltration separately |
| Approval substitution/replay | Canonical payload hash, proposer, tenant, policy version, expiry, consumed state | Tamper, expiry, role and duplicate tests | Real reviewer identity, review UI, authenticated audit and policy distribution are absent |
| Permission revoked after approval | Recheck creator and reviewer immediately before initial mutation | Revocation tests | Distributed identity cache freshness and external system revocation need validation |
| Duplicate or ambiguous request | One local transaction for effect/receipt/approval; request payload conflict | Concurrent duplicate and timeout-after-commit tests | External effects need downstream idempotency and reconciliation; no exactly-once claim |
| Crash or stale worker | Durable state and expected checkpoint version | Process restart, rollback and stale-writer tests | No distributed lease, fencing, schema migration or multi-region recovery |
| Stale retained content | Tenant/principal scope, source version, expiry and explicit deletion | Version/TTL/deletion tests | No automatic sweep or backup erasure workflow |
| Unbounded work or model invocation | Durable step reservation; local-model switch, scoped expiring approval and request/output limits | Exhaustion, concurrency, adapter-denial tests | No monetary ledger or paid-provider adapter; local model runtime must have egress denied externally |
| Sensitive trace leakage | Fixed events and allowlisted metadata, omit raw business content | Secret canary and scoped trace tests | No production collector, encryption, retention or log tamper resistance |
| Malicious source archive | SHA-256 check, fixed member reads, size limits, strict header, no path extraction | Checksum, schema, source ZIP tests; actual UCI profile | Run large untrusted files in constrained processes; a checksum alone does not authenticate source |
| Confidential or raw data publication | Ignore raw/full-derived data, publish only allowlisted profile fields | Static repository checks and release review | Review future changes and Git history; filename ignores are not a complete secret detector |

Security assertions are scoped to these executable tests. The audit hook in the offline wrapper is an acceptance diagnostic, not a security sandbox; [Python's documentation](https://docs.python.org/3.12/library/sys.html#sys.addaudithook) explicitly describes that limitation. No hidden model reasoning is retained. Credentials are not needed for the required track.
