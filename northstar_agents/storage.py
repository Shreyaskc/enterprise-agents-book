# SPDX-License-Identifier: MIT
"""Single-host transactional teaching store; not a distributed exactly-once claim."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterator

from .contracts import Context, Rejected, canonical, identifier
from .data import load_fixture

SCHEMA = """
CREATE TABLE IF NOT EXISTS principals (
 tenant TEXT, principal TEXT, permissions TEXT NOT NULL, active INTEGER NOT NULL,
 PRIMARY KEY(tenant, principal));
CREATE TABLE IF NOT EXISTS approvals (
 tenant TEXT, approval_id TEXT, proposer TEXT, approver TEXT, request_hash TEXT,
 expires REAL, used INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(tenant, approval_id));
CREATE TABLE IF NOT EXISTS ledger (
 tenant TEXT, request_key TEXT, request_hash TEXT, result TEXT,
 PRIMARY KEY(tenant, request_key));
CREATE TABLE IF NOT EXISTS local_cases (
 tenant TEXT, local_id TEXT, action TEXT, PRIMARY KEY(tenant, local_id));
CREATE TABLE IF NOT EXISTS checkpoints (
 tenant TEXT, principal TEXT, run_id TEXT, version INTEGER, state TEXT,
 PRIMARY KEY(tenant, principal, run_id));
CREATE TABLE IF NOT EXISTS memory (
 tenant TEXT, principal TEXT, memory_key TEXT, value TEXT, source_version TEXT,
 expires REAL, PRIMARY KEY(tenant, principal, memory_key));
CREATE TABLE IF NOT EXISTS budgets (
 tenant TEXT, principal TEXT, run_id TEXT, used INTEGER, maximum INTEGER,
 PRIMARY KEY(tenant, principal, run_id));
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT, principal TEXT,
 run_id TEXT, event TEXT, metadata TEXT);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:", *, now: Callable[[], float] = time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.now = now
        self.fixture = load_fixture()
        with self.transaction():
            for user in self.fixture["principals"]:
                self.db.execute("INSERT OR IGNORE INTO principals VALUES (?, ?, ?, 1)",
                                (user["tenant"], user["principal"], canonical(user["permissions"])))

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def require(self, ctx: Context, permission: str) -> None:
        row = self.db.execute("SELECT permissions, active FROM principals WHERE tenant=? AND principal=?",
                              (ctx.tenant, ctx.principal)).fetchone()
        if row is None or not row["active"] or permission not in json.loads(row["permissions"]):
            raise Rejected("permission_denied")

    def revoke(self, operator: Context, principal: str) -> None:
        identifier(principal)
        with self.transaction():
            self.require(operator, "principal.revoke")
            self.db.execute("UPDATE principals SET active=0 WHERE tenant=? AND principal=?",
                            (operator.tenant, principal))
            self.event(operator, "permission_revoked", {"status": "revoked"})

    def event(self, ctx: Context, event: str, metadata: dict, *, run_id: str = "standalone") -> None:
        # Construct metadata from fixed program values, never raw prompts or reasoning.
        if event not in {"tool_called", "case_created", "workflow_step", "approval_granted",
                         "permission_revoked", "memory_purged", "model_reserved"}:
            raise Rejected("invalid_event")
        if set(metadata) - {"tool", "state", "status", "version", "mode"}:
            raise Rejected("invalid_event_metadata")
        identifier(run_id)
        self.db.execute("INSERT INTO events(tenant,principal,run_id,event,metadata) VALUES(?,?,?,?,?)",
                        (ctx.tenant, ctx.principal, run_id, event, canonical(metadata)))

    def traces(self, ctx: Context) -> list[dict]:
        try:
            self.require(ctx, "trace.read")
            rows = self.db.execute("SELECT sequence,run_id,event,metadata FROM events WHERE tenant=? ORDER BY sequence",
                                   (ctx.tenant,))
        except Rejected:
            self.require(ctx, "trace.own")
            rows = self.db.execute("SELECT sequence,run_id,event,metadata FROM events WHERE tenant=? AND principal=? ORDER BY sequence",
                                   (ctx.tenant, ctx.principal))
        return [{"sequence": r["sequence"], "run_id": r["run_id"], "event": r["event"],
                 "metadata": json.loads(r["metadata"])} for r in rows]

    def reserve(self, ctx: Context, run_id: str, maximum: int) -> int:
        identifier(run_id)
        if type(maximum) is not int or maximum < 0 or maximum > 100:
            raise Rejected("invalid_budget")
        with self.transaction():
            self.require(ctx, "budget.use")
            self.db.execute("INSERT OR IGNORE INTO budgets VALUES(?,?,?,0,?)",
                            (ctx.tenant, ctx.principal, run_id, maximum))
            row = self.db.execute("SELECT used,maximum FROM budgets WHERE tenant=? AND principal=? AND run_id=?",
                                  (ctx.tenant, ctx.principal, run_id)).fetchone()
            if row["maximum"] != maximum:
                raise Rejected("budget_change_requires_new_run")
            if row["used"] >= row["maximum"]:
                raise Rejected("budget_exhausted")
            self.db.execute("UPDATE budgets SET used=used+1 WHERE tenant=? AND principal=? AND run_id=?",
                            (ctx.tenant, ctx.principal, run_id))
            return row["used"] + 1

    def remember(self, ctx: Context, key: str, value: str, source_version: str, ttl: int) -> None:
        identifier(key)
        identifier(source_version)
        if type(value) is not str or len(value) > 500 or type(ttl) is not int or not 0 < ttl <= 86400:
            raise Rejected("invalid_memory")
        with self.transaction():
            self.require(ctx, "memory.use")
            self.db.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?,?,?,?)",
                            (ctx.tenant, ctx.principal, key, value, source_version, self.now() + ttl))

    def recall(self, ctx: Context, key: str, source_version: str) -> dict:
        self.require(ctx, "memory.use")
        row = self.db.execute("SELECT value,source_version,expires FROM memory WHERE tenant=? AND principal=? AND memory_key=?",
                              (ctx.tenant, ctx.principal, key)).fetchone()
        if row is None:
            return {"status": "missing"}
        if row["expires"] <= self.now() or row["source_version"] != source_version:
            return {"status": "stale"}
        return {"status": "fresh", "value": row["value"]}

    def forget(self, ctx: Context, key: str) -> None:
        with self.transaction():
            self.require(ctx, "memory.use")
            self.db.execute("DELETE FROM memory WHERE tenant=? AND principal=? AND memory_key=?",
                            (ctx.tenant, ctx.principal, key))
            self.event(ctx, "memory_purged", {"status": "deleted"})

    def checkpoint(self, ctx: Context, run_id: str) -> tuple[int, dict]:
        identifier(run_id)
        self.require(ctx, "case.read")
        row = self.db.execute("SELECT version,state FROM checkpoints WHERE tenant=? AND principal=? AND run_id=?",
                              (ctx.tenant, ctx.principal, run_id)).fetchone()
        return (row["version"], json.loads(row["state"])) if row else (0, {"stage": "new"})

    def save_checkpoint(self, ctx: Context, run_id: str, expected: int, state: dict) -> None:
        # Caller owns transaction; compare-and-swap prevents stale writers.
        self.require(ctx, "case.read")
        if expected == 0:
            try:
                self.db.execute("INSERT INTO checkpoints VALUES(?,?,?,1,?)",
                                (ctx.tenant, ctx.principal, run_id, canonical(state)))
            except sqlite3.IntegrityError as exc:
                raise Rejected("checkpoint_conflict") from exc
        else:
            cur = self.db.execute("UPDATE checkpoints SET state=?,version=version+1 WHERE tenant=? AND principal=? AND run_id=? AND version=?",
                                  (canonical(state), ctx.tenant, ctx.principal, run_id, expected))
            if cur.rowcount != 1:
                raise Rejected("checkpoint_conflict")
