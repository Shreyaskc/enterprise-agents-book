# SPDX-License-Identifier: MIT
"""One evolving Northstar business case, from lookups to governed local action."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
import uuid

from .contracts import CaseAction, Context, Rejected, ToolCall, canonical, identifier, text
from .data import scoped
from .storage import Store

SERVICE = Context("northstar", "service-sam")
INVENTORY = Context("northstar", "inventory-ivy")
REVIEWER = Context("northstar", "reviewer-rhea")
PLATFORM = Context("northstar", "platform-pat")
OTHER = Context("harbor", "service-sam")


class Northstar:
    def __init__(self, store: Store):
        self.store = store

    def invoice(self, ctx: Context, invoice_id: str) -> dict:
        self.store.require(ctx, "invoice.read")
        return scoped(self.store.fixture["invoices"], ctx.tenant, "invoice_id", identifier(invoice_id))

    def case(self, ctx: Context, case_id: str) -> dict:
        self.store.require(ctx, "case.read")
        return scoped(self.store.fixture["cases"], ctx.tenant, "case_id", identifier(case_id))

    def baseline(self, ctx: Context = SERVICE) -> dict:
        case = self.case(ctx, "CASE-SYN-104")
        invoice = self.invoice(ctx, case["invoice_id"])
        return {"case_id": case["case_id"], "invoice_id": invoice["invoice_id"],
                "ordered": {"description": invoice["description"], "quantity": invoice["quantity"],
                            "unit_price_gbp": f'{invoice["unit_price_pence"] / 100:.2f}'},
                "invoice_total_gbp": f'{invoice["quantity"] * invoice["unit_price_pence"] / 100:.2f}',
                "customer_report": case["customer_report"], "delivery_status": "unknown",
                "decision": "investigate_and_propose_local_case_only", "refund_authorized": False}

    def retrieve(self, ctx: Context, query: str) -> dict:
        self.store.require(ctx, "policy.read")
        terms = set(re.findall(r"[a-z0-9]+", text(query).lower()))
        hits = []
        for doc in self.store.fixture["documents"]:
            # Authorization before ranking. Documents are data, never executable plans.
            if doc["tenant"] != ctx.tenant:
                continue
            body = doc["text"]
            # This teaching detector is deliberately narrow, not a general injection defense.
            if "ignore all previous instructions" in body.lower():
                continue
            score = len(terms & set(re.findall(r"[a-z0-9]+", body.lower())))
            if score:
                hits.append({"document_id": doc["document_id"], "version": doc["version"],
                             "source": doc["source"], "sha256": hashlib.sha256(body.encode()).hexdigest(),
                             "span": [0, len(body)], "quote": body, "score": score,
                             "source_kind": "invented_teaching_material"})
        hits.sort(key=lambda h: (-h["score"], h["document_id"]))
        return {"method": "lexical_overlap_not_embeddings", "evidence": hits[:3],
                "status": "supported" if hits else "abstain_no_authorized_evidence"}

    def sales_signal(self, ctx: Context, stock_code: str) -> dict:
        self.store.require(ctx, "sales.read")
        stock_code = identifier(stock_code)
        rows = [r for r in self.store.fixture["invoices"]
                if r["tenant"] == ctx.tenant and r["stock_code"] == stock_code]
        return {"stock_code": stock_code, "synthetic_units_sold": sum(r["quantity"] for r in rows),
                "inventory_on_hand": "unknown", "replenishment_quantity": "not_determined",
                "recommendation": "review_sales_and_obtain_inventory_data", "purchase_authorized": False}

    def tool(self, ctx: Context, call: ToolCall, *, run_id: str = "standalone") -> dict:
        call = call.validated()
        arg = next(iter(call.arguments.values()))
        handlers = {"lookup_invoice": self.invoice, "lookup_case": self.case,
                    "search_policy": self.retrieve, "sales_signal": self.sales_signal}
        result = handlers[call.name](ctx, arg)
        self.store.event(ctx, "tool_called", {"tool": call.name, "status": "completed"}, run_id=run_id)
        return result

    def agent(self, ctx: Context = SERVICE, *, question: str = "Investigate CASE-SYN-104",
              maximum_steps: int = 3, run_id: str | None = None) -> dict:
        text(question)
        run_id = run_id or uuid.uuid4().hex
        # Explicit rule planner. No model decides these calls; no document becomes code.
        calls = [ToolCall("lookup_case", {"case_id": "CASE-SYN-104"}),
                 ToolCall("lookup_invoice", {"invoice_id": "INV-SYN-4817"}),
                 ToolCall("search_policy", {"query": "returns purchase case"})]
        results = []
        for call in calls:
            self.store.reserve(ctx, run_id, maximum_steps)
            results.append({"tool": call.name, "result": self.tool(ctx, call, run_id=run_id)})
        return {"planner": "deterministic_rule_simulation", "steps": len(results),
                "results": results, "decision": "propose_reviewed_local_case",
                "delivery_status": "unknown", "refund_authorized": False}

    def validate_action(self, ctx: Context, action: CaseAction) -> CaseAction:
        action = action.validated()
        self.store.require(ctx, "case.propose")
        case = self.case(ctx, action.case_id)
        self.invoice(ctx, action.invoice_id)
        if case["invoice_id"] != action.invoice_id:
            raise Rejected("case_invoice_mismatch")
        if action.policy_version != self.store.fixture["policy_version"]:
            raise Rejected("stale_policy")
        return action

    def propose(self, ctx: Context = SERVICE) -> CaseAction:
        action = CaseAction("CASE-SYN-104", "INV-SYN-4817",
                            "Investigate reported red mug discrepancy; delivery remains unverified.")
        return self.validate_action(ctx, action)

    def approve(self, reviewer: Context, proposer: Context, action: CaseAction, *, ttl: int = 300) -> str:
        if type(ttl) is not int or not 0 < ttl <= 3600:
            raise Rejected("invalid_approval_expiry")
        with self.store.transaction():
            self.store.require(reviewer, "approval.grant")
            if reviewer.tenant != proposer.tenant or reviewer.principal == proposer.principal:
                raise Rejected("separation_of_duties")
            action = self.validate_action(proposer, action)
            approval_id = uuid.uuid4().hex
            self.store.db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,0)",
                                  (proposer.tenant, approval_id, proposer.principal, reviewer.principal,
                                   action.request_hash(proposer), self.store.now() + ttl))
            self.store.event(reviewer, "approval_granted", {"status": "approved"})
            return approval_id

    def execute(self, ctx: Context, action: CaseAction, approval_id: str, request_key: str,
                *, fault: str | None = None) -> dict:
        """Atomic local effect + receipt. Timeout-after-commit is safe to replay by key.

        External effects would require downstream idempotency and reconciliation.
        """
        identifier(request_key)
        identifier(approval_id)
        with self.store.transaction():
            self.store.require(ctx, "case.create")  # Rechecked even on receipt replay.
            action = action.validated()
            self.case(ctx, action.case_id)  # Current receipt-read access still required.
            request_hash = action.request_hash(ctx)
            row = self.store.db.execute("SELECT request_hash,result FROM ledger WHERE tenant=? AND request_key=?",
                                        (ctx.tenant, request_key)).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise Rejected("idempotency_conflict")
                return {**json.loads(row["result"]), "replayed": True}
            action = self.validate_action(ctx, action)  # New effects require current policy.
            approval = self.store.db.execute("SELECT * FROM approvals WHERE tenant=? AND approval_id=?",
                                             (ctx.tenant, approval_id)).fetchone()
            if approval is None or approval["used"] or approval["expires"] <= self.store.now():
                raise Rejected("approval_unavailable")
            if approval["proposer"] != ctx.principal or approval["request_hash"] != request_hash:
                raise Rejected("approval_payload_mismatch")
            self.store.require(Context(ctx.tenant, approval["approver"]), "approval.grant")
            local_id = "LOCAL-" + hashlib.sha256(f"{ctx.tenant}:{request_key}".encode()).hexdigest()[:12]
            result = {"local_case_id": local_id, "status": "created_locally", "replayed": False}
            self.store.db.execute("INSERT INTO local_cases VALUES(?,?,?)",
                                  (ctx.tenant, local_id, canonical(asdict(action))))
            if fault == "before_commit":
                raise RuntimeError("simulated_crash_before_commit")
            self.store.db.execute("INSERT INTO ledger VALUES(?,?,?,?)",
                                  (ctx.tenant, request_key, request_hash, canonical(result)))
            self.store.db.execute("UPDATE approvals SET used=1 WHERE tenant=? AND approval_id=?",
                                  (ctx.tenant, approval_id))
            self.store.event(ctx, "case_created", {"status": "created_locally"}, run_id=request_key)
        if fault == "timeout_after_commit":
            raise TimeoutError("simulated_timeout_after_local_commit")
        return result

    def workflow(self, ctx: Context, run_id: str, *, pause_after: str | None = None,
                 fault: str | None = None) -> dict:
        """Durable read-only investigation; does not grant an approval or execute action."""
        started_with_checkpoint = None
        while True:
            with self.store.transaction():
                version, state = self.store.checkpoint(ctx, run_id)
                if started_with_checkpoint is None:
                    started_with_checkpoint = version > 0
                if state["stage"] == "completed":
                    return {"state": state, "checkpoint_version": version, "resumed": started_with_checkpoint,
                            "result_kind": "historical_read_only_checkpoint", "fresh_action_authorization_required": True,
                            "policy_current": state.get("proposal", {}).get("policy_version") == self.store.fixture["policy_version"]}
                if state["stage"] == "new":
                    self.baseline(ctx)
                    next_state = {"stage": "purchase_checked", "case_id": "CASE-SYN-104"}
                elif state["stage"] == "purchase_checked":
                    evidence = self.retrieve(ctx, "returns purchase case")
                    if not evidence["evidence"]:
                        raise Rejected("missing_policy_evidence")
                    self.propose(ctx)
                    next_state = {"stage": "prepared", "case_id": "CASE-SYN-104", "policy_version": "v3"}
                elif state["stage"] == "prepared":
                    self.propose(ctx)  # Current permission/policy checks survive resumption.
                    next_state = {"stage": "completed", "proposal": asdict(self.propose(ctx)),
                                  "requires_reviewer_approval": True}
                else:
                    raise Rejected("invalid_checkpoint_state")
                self.store.save_checkpoint(ctx, run_id, version, next_state)
                self.store.event(ctx, "workflow_step", {"state": next_state["stage"], "version": version + 1}, run_id=run_id)
                if fault == "before_commit":
                    raise RuntimeError("simulated_workflow_crash_before_commit")
            if fault == "after_commit":
                raise RuntimeError("simulated_workflow_crash_after_commit")
            if next_state["stage"] == pause_after:
                return {"state": next_state, "checkpoint_version": version + 1, "paused": True}

    def operations(self, ctx: Context = PLATFORM) -> dict:
        self.store.require(ctx, "operations.read")
        return {"tenant": ctx.tenant,
                "local_case_count": self.store.db.execute("SELECT count(*) FROM local_cases WHERE tenant=?", (ctx.tenant,)).fetchone()[0],
                "checkpoint_count": self.store.db.execute("SELECT count(*) FROM checkpoints WHERE tenant=?", (ctx.tenant,)).fetchone()[0],
                "expired_approval_count": self.store.db.execute("SELECT count(*) FROM approvals WHERE tenant=? AND expires<=?", (ctx.tenant, self.store.now())).fetchone()[0],
                "deployment_status": "local_teaching_store_not_distributed_service"}
