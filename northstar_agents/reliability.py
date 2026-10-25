# SPDX-License-Identifier: MIT
"""Two local databases, an approved intent/outbox, and explicit reconciliation.

This simulates a separate destination; it is not a distributed exactly-once claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import tempfile
from threading import Barrier
import uuid

from .contracts import CaseAction, Context, Rejected, canonical, digest, exact_keys, identifier, text
from .service import REVIEWER, SERVICE, Northstar
from .storage import Store

NOTE = ("CASE-SYN-104: ordered two blue mugs at GBP 12.50 each; customer reports one red mug; "
        "fulfillment unknown. Synthetic investigation note only.")


@dataclass(frozen=True)
class CaseNote:
    case_id: str = "CASE-SYN-104"
    invoice_id: str = "INV-SYN-4817"
    note: str = NOTE
    policy_version: str = "v3"
    kind: str = "append_synthetic_case_note"
    schema_version: int = 1

    @classmethod
    def parse(cls, value: object) -> CaseNote:
        obj = exact_keys(value, {"case_id", "invoice_id", "note", "policy_version", "kind", "schema_version"})
        if type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or obj["kind"] != "append_synthetic_case_note":
            raise Rejected("invalid_note_schema")
        return cls(identifier(obj["case_id"]), identifier(obj["invoice_id"]), text(obj["note"]),
                   identifier(obj["policy_version"]))

    def envelope(self, ctx: Context) -> dict:
        return {"tenant": ctx.tenant, "principal": ctx.principal, "action": asdict(self.parse(asdict(self)))}


def validate_receipt(receipt: object, tenant: str, key: str, payload_hash: str) -> dict:
    if type(receipt) is not dict or set(receipt) not in [
        {"tenant", "request_key", "payload_hash", "destination_note_id", "status"},
        {"tenant", "request_key", "payload_hash", "destination_note_id", "status", "destination_replayed"}]:
        raise Rejected("invalid_destination_receipt")
    expected_id = "NOTE-" + hashlib.sha256(f"{tenant}:{key}".encode()).hexdigest()[:12]
    if (receipt["tenant"], receipt["request_key"], receipt["payload_hash"], receipt["destination_note_id"], receipt["status"]) != (
        tenant, key, payload_hash, expected_id, "stored_in_simulated_destination"):
        raise Rejected("receipt_identity_mismatch")
    if "destination_replayed" in receipt and type(receipt["destination_replayed"]) is not bool:
        raise Rejected("invalid_destination_receipt")
    return {k: v for k, v in receipt.items() if k != "destination_replayed"}


class Destination:
    """A simulated receiver with its own transaction and durable idempotency ledger."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS destination_notes (
          tenant TEXT, request_key TEXT, payload TEXT, PRIMARY KEY(tenant,request_key));
        CREATE TABLE IF NOT EXISTS destination_receipts (
          tenant TEXT, request_key TEXT, payload_hash TEXT, receipt TEXT, PRIMARY KEY(tenant,request_key));
        """)

    def close(self):
        self.db.close()

    def lookup(self, ctx: Context, key: str, payload_hash: str) -> dict | None:
        row = self.db.execute("SELECT payload_hash,receipt FROM destination_receipts WHERE tenant=? AND request_key=?",
                              (ctx.tenant, identifier(key))).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise Rejected("destination_idempotency_conflict")
        receipt = json.loads(row["receipt"])
        validate_receipt(receipt, ctx.tenant, key, payload_hash)
        note = self.db.execute("SELECT payload FROM destination_notes WHERE tenant=? AND request_key=?", (ctx.tenant, key)).fetchone()
        if note is None or digest(json.loads(note["payload"])) != payload_hash:
            raise Rejected("destination_ledger_corrupt")
        return receipt

    def deliver(self, envelope: dict, key: str, payload_hash: str, *, fault: str | None = None) -> dict:
        envelope = exact_keys(envelope, {"tenant", "principal", "action"})
        ctx = Context(envelope["tenant"], envelope["principal"])
        CaseNote.parse(envelope["action"])
        identifier(key)
        if digest(envelope) != payload_hash:
            raise Rejected("destination_digest_mismatch")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.lookup(ctx, key, payload_hash)
            if existing is not None:
                result = {**existing, "destination_replayed": True}
            else:
                receipt = {"destination_note_id": "NOTE-" + hashlib.sha256(f"{ctx.tenant}:{key}".encode()).hexdigest()[:12],
                           "tenant": ctx.tenant, "request_key": key, "payload_hash": payload_hash, "status": "stored_in_simulated_destination"}
                self.db.execute("INSERT INTO destination_notes VALUES(?,?,?)", (ctx.tenant, key, canonical(envelope)))
                self.db.execute("INSERT INTO destination_receipts VALUES(?,?,?,?)", (ctx.tenant, key, payload_hash, canonical(receipt)))
                if fault == "before_destination_commit":
                    raise RuntimeError("simulated_failure_before_destination_commit")
                result = {**receipt, "destination_replayed": False}
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        if fault == "timeout_after_destination_commit":
            raise TimeoutError("simulated_timeout_after_destination_commit")
        return result

    def count(self, ctx: Context, key: str) -> int:
        return self.db.execute("SELECT count(*) FROM destination_notes WHERE tenant=? AND request_key=?",
                               (ctx.tenant, key)).fetchone()[0]


class ReliabilityLab:
    def __init__(self, source: Path, destination: Path):
        if source.resolve() == destination.resolve():
            raise Rejected("destination_must_be_separate")
        self.source_path, self.destination_path = source, destination
        self.store = Store(source)
        self.app = Northstar(self.store)
        self.destination = Destination(destination)
        self.store.db.executescript("""
        CREATE TABLE IF NOT EXISTS note_intents (
          tenant TEXT, request_key TEXT, principal TEXT, payload_hash TEXT, payload TEXT, approval_id TEXT,
          PRIMARY KEY(tenant,request_key));
        CREATE TABLE IF NOT EXISTS note_reauthorizations (
          tenant TEXT, request_key TEXT, approval_id TEXT, PRIMARY KEY(tenant,request_key), UNIQUE(tenant,approval_id));
        CREATE TABLE IF NOT EXISTS note_outbox (
          tenant TEXT, request_key TEXT, state TEXT, attempts INTEGER, receipt TEXT,
          PRIMARY KEY(tenant,request_key),
          FOREIGN KEY(tenant,request_key) REFERENCES note_intents(tenant,request_key));
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.destination.close()
        self.store.close()

    def validate(self, ctx: Context, note: CaseNote) -> dict:
        note = CaseNote.parse(asdict(note))
        self.app.validate_action(ctx, CaseAction(note.case_id, note.invoice_id, note.note, note.policy_version))
        return note.envelope(ctx)

    def approve(self, ctx: Context, note: CaseNote, reviewer: Context = REVIEWER) -> str:
        with self.store.transaction():
            self.store.require(reviewer, "approval.grant")
            if reviewer.tenant != ctx.tenant or reviewer.principal == ctx.principal:
                raise Rejected("separation_of_duties")
            envelope = self.validate(ctx, note)
            approval = uuid.uuid4().hex
            self.store.db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,0)",
                                  (ctx.tenant, approval, ctx.principal, reviewer.principal, digest(envelope), self.store.now() + 300))
            return approval

    def enqueue(self, ctx: Context, note: CaseNote, approval_id: str, key: str, *, fault: str | None = None) -> dict:
        identifier(key)
        identifier(approval_id)
        with self.store.transaction():
            self.store.require(ctx, "case.create")
            envelope = self.validate(ctx, note)
            payload_hash = digest(envelope)
            existing = self.store.db.execute("SELECT payload_hash FROM note_intents WHERE tenant=? AND request_key=?", (ctx.tenant, key)).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise Rejected("source_idempotency_conflict")
                return {"status": "already_enqueued", "payload_hash": payload_hash}
            approval = self.store.db.execute("SELECT * FROM approvals WHERE tenant=? AND approval_id=?", (ctx.tenant, approval_id)).fetchone()
            if approval is None or approval["used"] or approval["expires"] <= self.store.now():
                raise Rejected("approval_unavailable")
            if approval["proposer"] != ctx.principal or approval["request_hash"] != payload_hash:
                raise Rejected("approval_payload_mismatch")
            self.store.require(Context(ctx.tenant, approval["approver"]), "approval.grant")
            self.store.db.execute("INSERT INTO note_intents VALUES(?,?,?,?,?,?)", (ctx.tenant, key, ctx.principal, payload_hash, canonical(envelope), approval_id))
            self.store.db.execute("INSERT INTO note_outbox VALUES(?,?,?,0,NULL)", (ctx.tenant, key, "pending"))
            self.store.db.execute("UPDATE approvals SET used=1 WHERE tenant=? AND approval_id=?", (ctx.tenant, approval_id))
            if fault == "before_intent_commit":
                raise RuntimeError("simulated_failure_before_intent_commit")
        return {"status": "enqueued", "payload_hash": payload_hash}

    def pending(self, ctx: Context, key: str) -> dict:
        """Current owner read authority for immutable historical intent, not dispatch authority."""
        self.store.require(ctx, "case.read")
        row = self.store.db.execute("""SELECT i.*,o.state,o.attempts,o.receipt FROM note_intents i
          JOIN note_outbox o USING(tenant,request_key) WHERE i.tenant=? AND i.request_key=? AND i.principal=?""",
                                    (ctx.tenant, identifier(key), ctx.principal)).fetchone()
        if row is None:
            raise Rejected("outbox_unavailable")
        envelope = json.loads(row["payload"])
        note = CaseNote.parse(envelope["action"])
        if envelope != note.envelope(ctx) or digest(envelope) != row["payload_hash"]:
            raise Rejected("intent_integrity_failure")
        self.app.case(ctx, note.case_id)
        return dict(row)

    def authorize_dispatch(self, ctx: Context, row: dict) -> None:
        self.store.require(ctx, "case.create")
        self.validate(ctx, CaseNote.parse(json.loads(row["payload"])["action"]))
        newer = self.store.db.execute("SELECT approval_id FROM note_reauthorizations WHERE tenant=? AND request_key=?",
                                      (ctx.tenant, row["request_key"])).fetchone()
        grant_id = newer["approval_id"] if newer else row["approval_id"]
        grant = self.store.db.execute("SELECT * FROM approvals WHERE tenant=? AND approval_id=?", (ctx.tenant, grant_id)).fetchone()
        if (grant is None or grant["expires"] <= self.store.now() or grant["request_hash"] != row["payload_hash"]
                or grant["proposer"] != ctx.principal or not grant["used"]):
            raise Rejected("approval_unavailable")
        self.store.require(Context(ctx.tenant, grant["approver"]), "approval.grant")

    def reauthorize(self, ctx: Context, key: str, approval_id: str) -> dict:
        """Explicit fresh approval consumed and bound to this immutable tenant/key/payload."""
        identifier(approval_id)
        with self.store.transaction():
            row = self.pending(ctx, key)
            self.store.require(ctx, "case.create")
            self.validate(ctx, CaseNote.parse(json.loads(row["payload"])["action"]))
            if row["state"] != "pending":
                raise Rejected("outbox_not_pending")
            grant = self.store.db.execute("SELECT * FROM approvals WHERE tenant=? AND approval_id=?", (ctx.tenant, approval_id)).fetchone()
            if grant is None or grant["used"] or grant["expires"] <= self.store.now():
                raise Rejected("approval_unavailable")
            if grant["proposer"] != ctx.principal or grant["request_hash"] != row["payload_hash"]:
                raise Rejected("approval_payload_mismatch")
            self.store.require(Context(ctx.tenant, grant["approver"]), "approval.grant")
            self.store.db.execute("UPDATE approvals SET used=1 WHERE tenant=? AND approval_id=?", (ctx.tenant, approval_id))
            self.store.db.execute("INSERT OR REPLACE INTO note_reauthorizations VALUES(?,?,?)", (ctx.tenant, key, approval_id))
        return {"status": "reauthorized", "request_key": key, "payload_hash": row["payload_hash"]}

    def acknowledge(self, ctx: Context, key: str, payload_hash: str, receipt: dict) -> dict:
        # Recovery records an existing effect. It cannot invoke deliver or authorize another effect.
        with self.store.transaction():
            row = self.pending(ctx, key)
            if row["payload_hash"] != payload_hash:
                raise Rejected("receipt_digest_mismatch")
            identity = validate_receipt(receipt, ctx.tenant, key, payload_hash)
            stored = self.destination.lookup(ctx, key, payload_hash)
            if stored is None or identity != validate_receipt(stored, ctx.tenant, key, payload_hash):
                raise Rejected("unverified_destination_receipt")
            self.store.db.execute("UPDATE note_outbox SET state='acknowledged',receipt=? WHERE tenant=? AND request_key=?",
                                  (canonical(receipt), ctx.tenant, key))
        return {"status": "acknowledged", "receipt": receipt}

    def dispatch(self, ctx: Context, key: str, *, fault: str | None = None) -> dict:
        with self.store.transaction():
            row = self.pending(ctx, key)
            if row["state"] == "acknowledged":
                return {"status": "already_acknowledged", "receipt": json.loads(row["receipt"])}
            self.authorize_dispatch(ctx, row)
            self.store.db.execute("UPDATE note_outbox SET attempts=attempts+1 WHERE tenant=? AND request_key=?", (ctx.tenant, key))
        # No source transaction spans the destination call. These commits are independent.
        try:
            receipt = self.destination.deliver(json.loads(row["payload"]), key, row["payload_hash"], fault=fault)
        except TimeoutError:
            return {"status": "uncertain_reconcile_before_retry", "source_state": "pending"}
        if fault == "after_response_before_receipt":
            raise RuntimeError("simulated_crash_after_response_before_local_receipt")
        return self.acknowledge(ctx, key, row["payload_hash"], receipt)

    def reconcile(self, ctx: Context, key: str) -> dict:
        row = self.pending(ctx, key)
        receipt = self.destination.lookup(ctx, key, row["payload_hash"])
        if receipt is None:
            return {"status": "no_destination_receipt", "source_state": row["state"],
                    "next_step": "Explicit reauthorization of the same immutable key/payload is required if approval expired. Changed policy or revoked authority requires an authorized manual review; do not dispatch or infer rollback."}
        return self.acknowledge(ctx, key, row["payload_hash"], receipt)

    def counts(self, ctx: Context, key: str) -> dict:
        return {"source_intents": self.store.db.execute("SELECT count(*) FROM note_intents WHERE tenant=? AND request_key=?", (ctx.tenant, key)).fetchone()[0],
                "source_outbox": self.store.db.execute("SELECT count(*) FROM note_outbox WHERE tenant=? AND request_key=?", (ctx.tenant, key)).fetchone()[0],
                "destination_notes": self.destination.count(ctx, key)}


def run_lab() -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="northstar-outbox-") as tmp:
        for fault in ["before_intent_commit", "before_destination_commit", "timeout_after_destination_commit", "after_response_before_receipt"]:
            directory = Path(tmp) / fault
            with ReliabilityLab(directory / "source.sqlite", directory / "destination.sqlite") as lab:
                note, key = CaseNote(), "note-104"
                approval = lab.approve(SERVICE, note)
                fault_observed = False
                if fault == "before_intent_commit":
                    try:
                        lab.enqueue(SERVICE, note, approval, key, fault=fault)
                    except RuntimeError:
                        fault_observed = True
                    intermediate = {**lab.counts(SERVICE, key),
                                    "approval_consumed": lab.store.db.execute("SELECT used FROM approvals WHERE tenant=? AND approval_id=?", (SERVICE.tenant, approval)).fetchone()[0]}
                    lab.enqueue(SERVICE, note, approval, key)
                    recovered = lab.dispatch(SERVICE, key)
                else:
                    lab.enqueue(SERVICE, note, approval, key)
                    try:
                        response = lab.dispatch(SERVICE, key, fault=fault)
                        fault_observed = response["status"] == "uncertain_reconcile_before_retry"
                    except RuntimeError:
                        fault_observed = True
                    intermediate = {**lab.counts(SERVICE, key), "source_state": lab.pending(SERVICE, key)["state"],
                                    "approval_consumed": lab.store.db.execute("SELECT used FROM approvals WHERE tenant=? AND approval_id=?", (SERVICE.tenant, approval)).fetchone()[0]}
                    recovered = lab.reconcile(SERVICE, key)
                    if recovered["status"] == "no_destination_receipt":
                        recovered = lab.dispatch(SERVICE, key)  # Explicit retry only after absence was observed.
                expected_intermediate = {"source_intents": 0 if fault == "before_intent_commit" else 1,
                                         "source_outbox": 0 if fault == "before_intent_commit" else 1,
                                         "approval_consumed": 0 if fault == "before_intent_commit" else 1,
                                         "destination_notes": 1 if fault in {"timeout_after_destination_commit", "after_response_before_receipt"} else 0}
                if fault != "before_intent_commit":
                    expected_intermediate["source_state"] = "pending"
                with ReliabilityLab(lab.source_path, lab.destination_path) as reopened:
                    final = reopened.counts(SERVICE, key)
                    final["source_state"] = reopened.pending(SERVICE, key)["state"]
                    final["receipt_matches_destination"] = (
                        validate_receipt(json.loads(reopened.pending(SERVICE, key)["receipt"] or "null"), SERVICE.tenant, key, digest(note.envelope(SERVICE)))
                        == reopened.destination.lookup(SERVICE, key, digest(note.envelope(SERVICE)))) if final["source_state"] == "acknowledged" else False
                    final["approval_consumed"] = reopened.store.db.execute("SELECT used FROM approvals WHERE tenant=? AND approval_id=?", (SERVICE.tenant, approval)).fetchone()[0]
                results.append({"scenario": fault, "fault_observed": fault_observed,
                                "expected_intermediate": expected_intermediate, "observed_intermediate": intermediate,
                                "recovery": recovered, "expected_final": {"source_intents": 1, "source_outbox": 1, "destination_notes": 1, "source_state": "acknowledged", "receipt_matches_destination": True, "approval_consumed": 1},
                                "observed_final": final,
                                "passed": fault_observed and intermediate == expected_intermediate and final == {"source_intents": 1, "source_outbox": 1, "destination_notes": 1, "source_state": "acknowledged", "receipt_matches_destination": True, "approval_consumed": 1}})
        directory = Path(tmp) / "duplicates"
        with ReliabilityLab(directory / "source.sqlite", directory / "destination.sqlite") as lab:
            note, key = CaseNote(), "note-104"
            lab.enqueue(SERVICE, note, lab.approve(SERVICE, note), key)
            simultaneous = Barrier(2)
            def dispatch(_):
                with ReliabilityLab(lab.source_path, lab.destination_path) as worker:
                    original = worker.destination.deliver
                    def synchronized_deliver(*args, **kwargs):
                        simultaneous.wait(timeout=5)
                        return original(*args, **kwargs)
                    worker.destination.deliver = synchronized_deliver
                    return worker.dispatch(SERVICE, key)
            with ThreadPoolExecutor(max_workers=2) as workers:
                responses = list(workers.map(dispatch, range(2)))
            counts = lab.counts(SERVICE, key)
            results.append({"scenario": "concurrent_duplicate_dispatch", "responses": responses,
                            "synchronization": "Two dispatcher calls meet at a bounded barrier before separate destination transactions.",
                            "destination_replay_flags": sorted(r["receipt"]["destination_replayed"] for r in responses),
                            "observed": counts, "passed": counts["destination_notes"] == 1 and lab.pending(SERVICE, key)["state"] == "acknowledged"
                            and sorted(r["receipt"]["destination_replayed"] for r in responses) == [False, True]})
            conflicting = replace(note, note="Changed note must not reuse the request key.")
            source_conflict = destination_conflict = False
            try:
                lab.enqueue(SERVICE, conflicting, lab.approve(SERVICE, conflicting), key)
            except Rejected as exc:
                source_conflict = str(exc) == "source_idempotency_conflict"
            envelope = conflicting.envelope(SERVICE)
            try:
                lab.destination.deliver(envelope, key, digest(envelope))
            except Rejected as exc:
                destination_conflict = str(exc) == "destination_idempotency_conflict"
            results.append({"scenario": "conflicting_key_reuse", "source_rejected": source_conflict,
                            "destination_rejected": destination_conflict, "passed": source_conflict and destination_conflict and lab.destination.count(SERVICE, key) == 1})
    from .evaluation import source_hash
    return {"artifact_kind": "observed_two_store_outbox_lab", "source_tree_sha256": source_hash(),
            "run_at_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
            "lab": "two_local_sqlite_stores_transactional_outbox", "note": NOTE,
            "approval_mode": "synthetic_reviewer_role", "scenario_count": len(results),
            "all_passed": all(r["passed"] for r in results), "results": results,
            "guarantee_tested": "Atomic source intent/outbox/approval consumption; one destination note per tenant/key with matching digest under tested local retries/races; reconciliation of observed acknowledgement loss.",
            "limitations": "Two local files and injected failures, not real network partitions, distributed exactly-once execution, production receiver authentication or multi-node fencing."}
