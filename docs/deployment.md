# Operations and enterprise design exercises

This is a local teaching process; no deployment is provisioned. Platform Engineering owns shared policy/runtime/storage standards, Service Operations owns case authority and Inventory Operations owns signal interpretation. Security/data owners review identity, tenant boundaries, data rights and retention; SRE owns recovery and incidents. These are suggested responsibilities, not claims about a real employer.

Practice read-only restart with a fresh local database, then inspect operations/trace output. Run the separate durability lab for approved synthetic note intent/outbox, a second destination ledger, ambiguity and reconciliation. Keep explicit approval binding and current authorization outside model control.

An enterprise design must validate authenticated principal/tenant mapping, separate reviewer sessions, per-tool credentials and egress, durable queues/outbox, worker leases/fencing, downstream idempotency and reconciliation ownership. Test backup restore, migrations/rollback, revocation, retention/erasure, log access and incident procedures in the intended environment. Local SQLite tests do not establish those production guarantees.

The public static-check workflow requests read-only permissions and uses pinned upstream Actions. No personal self-hosted runner configuration is included. Do not route untrusted public pull-request code onto a private machine or expose its credentials/data. Keep book/diagram build automation in the private source repository.
