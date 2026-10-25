# SPDX-License-Identifier: MIT
"""Stable lab commands; every default path is offline and has zero model calls."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .adapters import PLAN_SCHEMA
from .contracts import Rejected
from .evaluation import denied, evaluate, mutation_count
from .ingest import download_source, ingest
from .service import INVENTORY, OTHER, PLATFORM, REVIEWER, SERVICE, Northstar
from .storage import Store
from .reporting import ReportReservation, write_report

STAGES = ("glossary", "baseline", "retrieve", "agent", "memory", "workflow", "approvals",
          "evaluate", "teams", "platform", "operations", "capstone", "trace", "adapter-schema", "durability-lab")



def demonstration(stage: str, app: Northstar, args: argparse.Namespace) -> dict:
    s = app.store
    if stage == "glossary":
        return {"workflow": "Code fixes the state transitions and sequence.",
                "agent": "A planner selects bounded actions; the default lab planner is a deterministic simulation.",
                "tool": "A typed capability with runtime validation and authorization.",
                "retrieval": "Find permitted evidence and preserve its source; retrieval is not proof of delivery.",
                "memory": "Scoped retained state with a purpose, source version, expiry and deletion path.",
                "routing": "Choose a specialist for a request.", "handoff": "Transfer a bounded task and permitted context.",
                "multi_agent": "Multiple specialist roles; not inherently better than a single workflow.",
                "tracks": ["understand_the_concept", "build_the_local_example", "design_for_enterprise_deployment"]}
    if stage == "baseline":
        return app.baseline()
    if stage == "durability-lab":
        from .reliability import run_lab
        return run_lab()
    if stage == "retrieve":
        return app.retrieve(SERVICE, args.query)
    if stage == "agent":
        return app.agent(question=args.question, maximum_steps=args.maximum_steps)
    if stage == "memory":
        s.remember(SERVICE, "case-note", "Canonical synthetic policy v3 summary", "v3", 60)
        stale = s.recall(SERVICE, "case-note", "v4")
        s.remember(SERVICE, "case-note", "Branch-only synthetic policy v4 summary", "v4", 60)
        fresh = s.recall(SERVICE, "case-note", "v4")
        isolated = s.recall(OTHER, "case-note", "v4")
        s.forget(SERVICE, "case-note")
        return {"stale": stale, "fresh": fresh, "harbor_view": isolated,
                "branch_policy_version": "v4", "canonical_policy_version": s.fixture["policy_version"],
                "after_deletion": s.recall(SERVICE, "case-note", "v4")}
    if stage == "workflow":
        return app.workflow(SERVICE, args.run_id, pause_after=args.pause_after)
    if stage == "approvals":
        action = app.propose()
        approval_id = app.approve(REVIEWER, SERVICE, action)
        first = app.execute(SERVICE, action, approval_id, "lab07")
        replay = app.execute(SERVICE, action, approval_id, "lab07")
        return {"proposal": asdict(action), "reviewer": "synthetic_reviewer_role_not_a_real_human_review",
                "first": first, "repeat": replay, "local_mutations": mutation_count(s), "refund_authorized": False}
    if stage == "teams":
        return {"tenant": "northstar", "router": "deterministic_rule_simulation",
                "service_operations": app.agent(), "inventory_operations": app.sales_signal(INVENTORY, "MUG-BLUE-SYN"),
                "handoff": "Read-only specialist results combined by trusted code; roles do not inherit each other's permissions."}
    if stage == "platform":
        return {"northstar_teams": ["service_operations", "inventory_operations", "platform_engineering"],
                "isolation_tenant": "harbor", "cross_tenant_invoice_denied": denied(lambda: app.invoice(SERVICE, "INV-OTHER-9000")),
                "service_to_inventory_denied": denied(lambda: app.sales_signal(SERVICE, "MUG-BLUE-SYN")),
                "inventory_to_service_denied": denied(lambda: app.case(INVENTORY, "CASE-SYN-104")),
                "platform_business_data_denied": denied(lambda: app.invoice(PLATFORM, "INV-SYN-4817"))}
    if stage == "operations":
        return {**app.operations(), "runbook": "docs/deployment.md",
                "controls": ["backup_and_restore", "permission_revocation", "approval_expiry", "budget_limits", "reconciliation"]}
    if stage == "trace":
        return {"events": s.traces(PLATFORM), "contains_hidden_model_reasoning": False}
    if stage == "adapter-schema":
        return {"adapter": "ollama_loopback_only", "planning_protocol": "schema_constrained_action_proposal",
                "live_test_scope": "schema_only_no_live_result_bundled", "schema": PLAN_SCHEMA}
    if stage == "capstone":
        investigation = app.agent()
        workflow = app.workflow(SERVICE, "capstone")
        action = app.propose()
        approval_id = app.approve(REVIEWER, SERVICE, action)
        result = app.execute(SERVICE, action, approval_id, "capstone")
        return {"investigation": investigation, "workflow": workflow,
                "approval_mode": "synthetic_reviewer_role_not_a_real_human_review",
                "local_action": result, "inventory_signal": app.sales_signal(INVENTORY, "MUG-BLUE-SYN"),
                "isolation": demonstration("platform", app, args), "trace": s.traces(PLATFORM),
                "regression": evaluate(), "production_ready": False}
    raise Rejected("unknown_stage")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Northstar enterprise agent labs: offline walkthroughs")
    commands = p.add_subparsers(dest="stage", required=True)
    for stage in STAGES:
        sub = commands.add_parser(stage)
        sub.add_argument("--db", default=":memory:", help="Local state; use a file for restart demonstrations")
        if stage == "retrieve":
            sub.add_argument("--query", default="returns purchase case")
        if stage == "agent":
            sub.add_argument("--question", default="Investigate CASE-SYN-104")
            sub.add_argument("--maximum-steps", type=int, default=3)
        if stage == "workflow":
            sub.add_argument("--run-id", default="lab06")
            sub.add_argument("--pause-after", choices=["purchase_checked", "prepared"])
        if stage == "evaluate":
            sub.add_argument("--output")
        if stage in {"capstone", "durability-lab"}:
            sub.add_argument("--report")
    sub = commands.add_parser("ingest-uci", help="Explicit optional UCI import, never run by examples")
    sub.add_argument("--input", required=True, help="Local workbook or download destination")
    sub.add_argument("--expected-sha256", required=True, help="Independently reviewed source archive/workbook checksum")
    sub.add_argument("--output", required=True)
    sub.add_argument("--download", action="store_true")
    sub.add_argument("--source-reviewed", action="store_true", help="You reviewed the source/rights; sends no license consent")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report_path = getattr(args, 'output', None) if args.stage == 'evaluate' else getattr(args, 'report', None)
        reservation = ReportReservation(report_path) if report_path else None
        if args.stage == "ingest-uci":
            if args.download:
                download_source(Path(args.input), source_reviewed=args.source_reviewed)
            result = {"schema_version": 1, "execution_mode": "explicit_uci_ingestion", "model_calls": 0,
                      **ingest(Path(args.input), args.expected_sha256, Path(args.output))}
        elif args.stage == "evaluate":
            result = evaluate()
        else:
            with Store(args.db) as store:
                result = {"schema_version": 1, "execution_mode": "deterministic_simulation", "model_calls": 0,
                          "fixture_kind": "invented_teaching_material_not_uci", "stage": args.stage,
                          **demonstration(args.stage, Northstar(store), args)}
        if reservation:
            try:
                reservation.write(result)
            except OSError as exc:
                # The completed result/receipt survives an evidence-storage error; no rollback claim.
                print(json.dumps({"status": "result_available_report_failed", "report_error": type(exc).__name__, "result": result}, indent=2))
                return 3
        print(json.dumps(result, indent=2, sort_keys=True))
        failed = args.stage == "evaluate" and not result["all_passed"]
        failed |= args.stage == "capstone" and not result["regression"]["all_passed"]
        failed |= args.stage == "durability-lab" and not result["all_passed"]
        return 1 if failed else 0
    except (Rejected, FileExistsError, OSError, ValueError) as exc:
        # Do not echo a secret-bearing input, arbitrary filesystem path, or provider response.
        code = str(exc) if isinstance(exc, Rejected) else type(exc).__name__
        print(json.dumps({"schema_version": 1, "status": "rejected", "code": code}), file=sys.stderr)
        return 2
