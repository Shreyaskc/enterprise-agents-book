# Implemented architecture and recommended extensions

The application uses one case across small command entry points, rather than disconnected snippets. `cli.py` composes the same `Northstar` service, strict contracts, fixture loader and SQLite store at progressively greater depth. The command map is versioned in [lab-index.json](lab-index.json).

## What the code does

`contracts.py` validates exact JSON fields, sizes, identifier syntax, schema versions and allowlisted tools. Dataclass annotations are supplemented by explicit parsers. `Context` is separate from tool arguments. A caller cannot obtain another tenant by adding `tenant` to a tool call.

`service.py` looks up scoped synthetic cases and invoices. Retrieval filters by tenant before lexical ranking, returns source URI, version, text span and SHA-256, and abstains if no allowed terms match. The narrow injection sample detector is demonstrative; the more consequential boundary is that documents are never interpreted as instructions or executable plans.

The deterministic planner makes three fixed read-only tool calls. This is a simulation of the tool-selection seam, not a trained model or free-form autonomous planner. The specialist command uses trusted code to call Service Operations and Inventory Operations under distinct roles in the same Northstar tenant. Harbor is a separate tenant. No specialist inherits the other team's permissions.

`storage.py` persists scoped memory, approvals, checkpoints, budget reservations, idempotency receipts and events. Mutations use explicit `BEGIN IMMEDIATE` transactions. Local case creation, approval consumption and receipt insertion share one database commit. Concurrent local retries are covered by tests; an external system is outside that commit.

`reliability.py` separately implements the [two-store outbox lab](reliability-lab.md). The source atomically commits an approved synthetic note intent and outbox row; a second local database applies the note under a tenant/key/digest ledger. Dispatch and acknowledgement are independent source/destination commits. Injected failures and reconciliation are executed locally, including a bounded duplicate-dispatch race. This is not a real external integration or distributed exactly-once guarantee.

Approvals bind tenant, proposer, exact canonical action payload, policy version and expiry. Only the synthetic reviewer role may grant one; the proposer cannot grant their own. Current creator and reviewer permissions are checked before the initial effect. Receipt replay rechecks the requesting principal's current permission. Revocation remains persisted when the store is reopened.

Traces contain scoped sequence, run ID, event name and allowlisted metadata. They omit prompts, customer reports, summaries, memory values, provider response bodies and hidden model reasoning. This is a small JSON trace format, not an OpenTelemetry integration.

## Workflow, agent and team choices

| Choice | In this repository | When to consider it; architectural recommendation |
| --- | --- | --- |
| Workflow | Fixed `new → purchase_checked → prepared → completed` transitions | Prefer explicit transitions when the business sequence and required approvals are known |
| Planning | Three-call deterministic rule planner | Use a model only when variable tool selection adds measured value; keep validation and policy outside it |
| Routing | Fixed request-to-specialist composition in `teams` | Route work when skills/data permissions differ; routing alone does not require several autonomous agents |
| Handoff | Read-only scoped specialist results returned to trusted coordinator | Pass the minimum context and capability needed; preserve provenance and budgets |
| Multi-agent design | Service and Inventory roles composed in a simulation | Evaluate added quality against handoff complexity, cost, failure handling and access boundaries |
| Retrieval | Lexical overlap with cited local policy | Establish an inspectable baseline before comparing embeddings or a vector store |

These are design recommendations, not measured comparative performance claims. The repository has no autonomous multi-model negotiation, semantic retrieval, or hidden chain-of-thought trace.

## Technology and version inventory

| Technology | Role | Verified scope |
| --- | --- | --- |
| CPython 3.12.13 and 3.14.6 | Runtime, standard-library unittest and JSON | Fresh runtime reports required for this staging export |
| SQLite 3.53.1 / 3.53.4 through those interpreters | Local persistent state and transactional demonstration | Actual rollback, restart, duplicate and concurrency tests |
| Standard-library `urllib.request` | Optional HTTP seam and explicit source download | Test doubles, actual UCI download and bounded local-model requests |
| Ollama 0.34.0 `/api/chat` | Optional schema-constrained action proposal adapter | Existing `gemma4:12b-mlx`, manifest digest in live reports; optional bounded checks; rerun before publication; no weights installed |
| GitHub Actions | Hosted test configuration | Action commits pinned; no hosted CI run exists for this staging export |
| Agent framework / vector database / provider SDK | None | No dependency to install, lock or claim tested |

Primary implementation references: [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html), [Python audit hooks](https://docs.python.org/3.12/library/sys.html#sys.addaudithook), and [Ollama chat API](https://docs.ollama.com/api/chat). Exact runtime versions and reproducibility commands are recorded separately.

## Enterprise recommendations requiring validation

Use a verified identity gateway; isolate worker credentials and egress; put tenant policy and quotas in a shared control plane; scope tools and storage in the execution plane. Select a transactional durable store, worker lease/recovery design, queue/outbox and downstream idempotency protocol appropriate to the real system. Apply database/runtime isolation beyond application predicates, because file access bypasses this local teaching store's controls.

Review policy changes, evaluation datasets and tool versions centrally. Keep per-tenant data lifecycle and trace authorization explicit. Before deployment, validate multi-node concurrency, identity revocation, secrets, migration/rollback, backup restoration, reconciliation, capacity and incident handling. None of those enterprise deployment properties follows automatically from passing the local suite.
