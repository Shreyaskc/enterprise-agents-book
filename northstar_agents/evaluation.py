# SPDX-License-Identifier: MIT
"""Local regression evidence. Measures deterministic behavior, not LLM quality."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import platform
import sqlite3
from pathlib import Path
import tempfile

from .contracts import Rejected, ToolCall, canonical
from .data import FIXTURE, ROOT
from .service import INVENTORY, PLATFORM, REVIEWER, SERVICE, Northstar
from .storage import Store
from .coverage import load_contract
from .provenance import git_metadata


def denied(fn) -> bool:
    try:
        fn()
    except Rejected:
        return True
    return False


def mutation_count(store: Store) -> int:
    return store.db.execute("SELECT count(*) FROM local_cases").fetchone()[0]


def observe(case_id: str, app: Northstar) -> dict:
    s = app.store
    if case_id == "purchase_baseline":
        r = app.baseline()
        return {"total": r["invoice_total_gbp"], "delivery": r["delivery_status"], "refund": r["refund_authorized"]}
    if case_id == "retrieval_provenance":
        hits = app.retrieve(SERVICE, "returns purchase case")["evidence"]
        return {"documents": [h["document_id"] for h in hits],
                "hash_valid": all(hashlib.sha256(h["quote"].encode()).hexdigest() == h["sha256"] for h in hits)}
    if case_id == "bounded_agent":
        r = app.agent()
        return {"steps": r["steps"], "refund": r["refund_authorized"]}
    if case_id == "tenant_isolation":
        rejected = denied(lambda: app.invoice(SERVICE, "INV-OTHER-9000"))
        output = canonical(app.retrieve(SERVICE, "returns HARBOR_CANARY"))
        return {"denied": rejected, "canary_leaked": "HARBOR_CANARY" in output}
    if case_id == "document_injection":
        output = app.agent()
        return {"injected_document_used": "SUSPICIOUS_DOCUMENT_CANARY" in canonical(output), "mutations": mutation_count(s)}
    if case_id in {"approval_binding", "permission_revocation", "duplicate_request", "timeout_after_commit"}:
        action = app.propose()
        approval = app.approve(REVIEWER, SERVICE, action)
        if case_id == "approval_binding":
            tamper = denied(lambda: app.execute(SERVICE, replace(action, summary="Changed action"), approval, "evaluation"))
            result = app.execute(SERVICE, action, approval, "evaluation")
            return {"tamper_denied": tamper, "valid_action_succeeds": result["status"] == "created_locally", "mutations": mutation_count(s)}
        if case_id == "permission_revocation":
            s.revoke(PLATFORM, SERVICE.principal)
            return {"denied": denied(lambda: app.execute(SERVICE, action, approval, "evaluation")), "mutations": mutation_count(s)}
        timeout = False
        try:
            app.execute(SERVICE, action, approval, "evaluation",
                        fault="timeout_after_commit" if case_id == "timeout_after_commit" else None)
        except TimeoutError:
            timeout = True
        result = app.execute(SERVICE, action, approval, "evaluation")
        result = {"replayed": result["replayed"], "mutations": mutation_count(s)}
        if case_id == "timeout_after_commit":
            result["timeout_observed"] = timeout
        return result
    if case_id == "crash_recovery":
        crashed = False
        try:
            app.workflow(SERVICE, "evaluation", fault="after_commit")
        except RuntimeError:
            crashed = True
        result = app.workflow(SERVICE, "evaluation")
        return {"crash_observed": crashed, "completed": result["state"]["stage"] == "completed",
                "approval_required": result["state"]["requires_reviewer_approval"]}
    if case_id == "stale_memory":
        s.remember(SERVICE, "policy-note", "v2 obsolete instruction", "v2", 30)
        result = s.recall(SERVICE, "policy-note", "v3")
        return {"status": result["status"], "value_disclosed": "value" in result}
    if case_id == "budget_exhaustion":
        rejected = denied(lambda: app.agent(maximum_steps=2))
        return {"denied": rejected, "tool_events": len(s.traces(SERVICE))}
    if case_id == "team_permissions":
        r = app.sales_signal(INVENTORY, "MUG-BLUE-SYN")
        return {"units": r["synthetic_units_sold"],
                "service_access_denied": denied(lambda: app.sales_signal(SERVICE, "MUG-BLUE-SYN")),
                "stock_unknown": r["inventory_on_hand"] == "unknown"}
    raise Rejected("unknown_evaluation_case")


def source_hash() -> str:
    hash_ = hashlib.sha256()
    for directory in ("northstar_agents", "data/fixtures", "data/manifests", "evals/cases", "tests", "scripts"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix not in {".py", ".json"} or "__pycache__" in path.parts:
                continue
            hash_.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    return hash_.hexdigest()


def evaluate() -> dict:
    path = ROOT / "evals/cases/regression.json"
    try:
        cases = load_contract(path, 'regression')
    except Rejected as exc:
        return {"schema_version": 1, "artifact_kind": "deterministic_regression_report", "status": "invalid_contract",
                "error_code": str(exc), "all_passed": False, "sample_count": 0, "passed_count": 0, "results": [],
                "model_calls": 0, "execution_mode": "deterministic_simulation", "source_tree_sha256": source_hash()}
    results = []
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="northstar-eval-") as tmp:
            with Store(Path(tmp) / "state.sqlite") as store:
                try:
                    actual = observe(case["id"], Northstar(store))
                    passed = actual == case["expected"]
                except Exception as exc:
                    actual, passed = {"error_type": type(exc).__name__}, False
        results.append({"id": case["id"], "expected": case["expected"], "observed": actual, "passed": passed})
    return {"schema_version": 1, "artifact_kind": "deterministic_regression_report",
            "execution_mode": "deterministic_simulation", "model_calls": 0,
            "run_at_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version, **git_metadata(ROOT),
            "source_tree_sha256": source_hash(), "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "cases_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sample_count": len(results),
            "passed_count": sum(r["passed"] for r in results), "all_passed": all(r["passed"] for r in results),
            "results": results, "limitations": "Deterministic fixture checks; no model quality, ROI, or distributed guarantees measured."}
