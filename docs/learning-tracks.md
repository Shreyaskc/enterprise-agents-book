# Three learning tracks

The same business case supports three depths. Readers can stop after understanding a concept; nobody needs to become a Kubernetes expert to follow a mug investigation. Technical ownership is a proposed division of responsibilities, not a staffing claim about a real company.

| Track | Prerequisites | Work and depth | What completion establishes |
| --- | --- | --- | --- |
| Understand the concept | None; read the case and distinguish a claim from evidence | Read each lab question, inspect one output, explain why a control exists | Understanding of the demonstrated idea |
| Build the local example | Shell, basic Python, JSON; SQL/state machines introduced before durability | Run the command, inspect the linked module, change a fixture in a separate branch, run relevant tests | Observed behavior of this local implementation |
| Design for enterprise deployment | Identity/security, data governance, distributed services, operational ownership | Review threats, design external control boundaries, validate infrastructure and incident procedures | A design to review and test; not production certification |

| Labs | Understand | Build prerequisites and focus | Enterprise depth and owner |
| --- | --- | --- | --- |
| 1 | Workflow, tool, agent, routing, planning and handoff | Shell/JSON; inspect `glossary` | Product lead defines permitted outcomes; all teams agree on terminology |
| 2 | Purchase evidence is not delivery evidence | Python dictionaries and integer money; `data.py`, `baseline` | Data steward reviews provenance/rights; application owner defines the evidence boundary |
| 3 | Retrieval should cite an allowed source or abstain | Text matching and hashes; `Northstar.retrieve` | Retrieval/data owner reviews access filters, source lifecycle and evaluation coverage |
| 4 | A bounded planner selects typed capabilities | Functions, strict JSON parsing; `contracts.py`, `agent` | Application/security owners restrict tools, egress and budgets |
| 5 | Memory expires, becomes stale, and can be deleted | State/expiry; `Store.remember`, `recall`, `forget`; isolated v4 branch | Privacy/data owner defines purpose, retention, erasure and source refresh |
| 6 | A restarted process needs durable state; a pending outbox does not prove destination absence | SQL transactions and state machines; `workflow`, checkpoint compare-and-swap, separate `durability-lab` | Backend/SRE own leases, migrations, backups, destination idempotency and reconciliation |
| 7 | A valid proposal is not an approval | Authorization, canonical payload hashes, ledger; `approve`, `execute` | Business reviewer owns approval authority; security supplies authenticated identity and revocation |
| 8 | Tests and measurements support different claims | Assertions and rubrics; local `evaluation.py`, scoped trace | Quality owner owns held-out evidence; SRE owns redaction, access and alerts |
| 9 | More specialists create more boundaries | Routing and role scopes; `teams` | Service/Inventory owners define handoff contract; platform prevents privilege inheritance |
| 10 | Team isolation differs from tenant isolation | Composite keys, authorization, negative cases; `platform` | Platform/security define identity, policy distribution, runtime isolation and data boundaries |
| 11 | Deploying creates operational obligations | Runbook, backup/restore, failure drill | SRE/platform own deployment, secrets, monitoring, incidents, capacity and rollback |
| 12 | Follow one case end to end | Prior local labs; `capstone`, test reports | Cross-functional review of residual risks and evidence before a rollout decision |

All default commands simulate planning deterministically. Approval demos simulate a reviewer identity. Optional model checks require explicit local approval. This staging export includes no private validation records; fresh execution evidence belongs to its reviewed snapshot and is kept separately from the source archive. Coordinated review rounds remain a distinct gate.
