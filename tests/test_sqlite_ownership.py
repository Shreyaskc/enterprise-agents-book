# SPDX-License-Identifier: MIT
"""Real retained SQLite handles prove ownership; no GC or warning suppression."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import inspect
import io
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from northstar_agents import data, storage
from northstar_agents.contracts import Rejected
from northstar_agents.data import ROOT
from northstar_agents.reliability import Destination, ReliabilityLab
from northstar_agents.storage import Store

REAL_CONNECT = sqlite3.connect


class SQLiteOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.handles: list[sqlite3.Connection] = []
        self.addCleanup(self.close_retained_handles)

    def close_retained_handles(self):
        for connection in self.handles:
            connection.close()

    def tracked_connect(self, *args, **kwargs):
        connection = REAL_CONNECT(*args, **kwargs)
        self.handles.append(connection)  # Strong reference intentionally survives the failure.
        return connection

    def deny_sql(self, action, table=None):
        def connect(*args, **kwargs):
            connection = self.tracked_connect(*args, **kwargs)
            connection.set_authorizer(
                lambda code, arg1, arg2, database, trigger:
                    sqlite3.SQLITE_DENY if code == action and (table is None or arg1 == table)
                    else sqlite3.SQLITE_OK
            )
            return connection
        return connect

    def assert_closed(self, connection):
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            connection.execute("SELECT 1")

    def assert_all_closed(self, expected_count):
        self.assertEqual(len(self.handles), expected_count)
        for connection in self.handles:
            self.assert_closed(connection)

    def test_store_fixture_checksum_rejection_closes_handle_before_caller_catches(self):
        bad_fixture = self.directory / "invalid-synthetic-fixture.json"
        bad_fixture.write_text("{}")
        with patch("sqlite3.connect", self.tracked_connect), patch.object(data, "FIXTURE", bad_fixture):
            try:
                Store(self.directory / "store.sqlite")
            except Rejected as exc:
                self.assertEqual(str(exc), "fixture_checksum_mismatch")
                self.assert_all_closed(1)
            else:
                self.fail("The actual fixture checksum rejection must propagate")

    def test_store_pragma_failure_closes_retained_real_handle(self):
        with patch("sqlite3.connect", self.deny_sql(sqlite3.SQLITE_PRAGMA)):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                Store(self.directory / "store.sqlite")
        self.assert_all_closed(1)

    def test_store_schema_failure_closes_retained_real_handle(self):
        with patch("sqlite3.connect", self.tracked_connect), patch.object(storage, "SCHEMA", "THIS IS INVALID SQL;"):
            with self.assertRaises(sqlite3.OperationalError):
                Store(self.directory / "store.sqlite")
        self.assert_all_closed(1)

    def test_store_principal_seed_failure_closes_and_preserves_transaction_rollback(self):
        with patch("sqlite3.connect", self.deny_sql(sqlite3.SQLITE_INSERT, "principals")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                Store(self.directory / "store.sqlite")
        self.assert_all_closed(1)
        connection = self.tracked_connect(self.directory / "store.sqlite")
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM principals").fetchone()[0], 0)
        finally:
            connection.close()

    def test_destination_schema_failure_closes_retained_real_handle(self):
        with patch("sqlite3.connect", self.deny_sql(sqlite3.SQLITE_CREATE_TABLE)):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                Destination(self.directory / "destination.sqlite")
        self.assert_all_closed(1)

    def test_lab_application_setup_failure_closes_store_before_destination_acquisition(self):
        failure = RuntimeError("synthetic_application_setup_failure")
        with patch("sqlite3.connect", self.tracked_connect), patch("northstar_agents.reliability.Northstar", side_effect=failure):
            with self.assertRaises(RuntimeError) as observed:
                ReliabilityLab(self.directory / "source.sqlite", self.directory / "destination.sqlite")
        self.assertIs(observed.exception, failure)
        self.assert_all_closed(1)

    def test_lab_destination_open_failure_closes_already_acquired_store(self):
        unavailable = self.directory / "destination-is-directory"
        unavailable.mkdir()
        with patch("sqlite3.connect", self.tracked_connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, "unable to open database"):
                ReliabilityLab(self.directory / "source.sqlite", unavailable)
        self.assert_all_closed(1)

    def test_lab_destination_setup_failure_closes_both_real_handles(self):
        def connect(*args, **kwargs):
            connection = self.tracked_connect(*args, **kwargs)
            if len(self.handles) == 2:
                connection.set_authorizer(lambda action, *rest: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE else sqlite3.SQLITE_OK)
            return connection
        with patch("sqlite3.connect", connect):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                ReliabilityLab(self.directory / "source.sqlite", self.directory / "destination.sqlite")
        self.assert_all_closed(2)

    def test_lab_outbox_schema_failure_closes_both_successfully_acquired_resources(self):
        def connect(*args, **kwargs):
            connection = self.tracked_connect(*args, **kwargs)
            if len(self.handles) == 1:
                connection.set_authorizer(lambda action, table, *rest: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and table == "note_intents" else sqlite3.SQLITE_OK)
            return connection
        with patch("sqlite3.connect", connect):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                ReliabilityLab(self.directory / "source.sqlite", self.directory / "destination.sqlite")
        self.assert_all_closed(2)

    def test_lab_exit_closes_store_even_if_destination_close_raises_after_closing(self):
        with patch("sqlite3.connect", self.tracked_connect):
            lab = ReliabilityLab(self.directory / "source.sqlite", self.directory / "destination.sqlite")
        real_close = lab.destination.close
        failure = RuntimeError("synthetic_destination_close_failure")
        def close_then_raise():
            real_close()
            raise failure
        with patch.object(lab.destination, "close", close_then_raise):
            with self.assertRaises(RuntimeError) as observed:
                lab.__exit__()
        self.assertIs(observed.exception, failure)
        self.assert_all_closed(2)

    def test_lab_exit_attempts_store_cleanup_when_destination_cannot_close(self):
        with patch("sqlite3.connect", self.tracked_connect):
            lab = ReliabilityLab(self.directory / "source.sqlite", self.directory / "destination.sqlite")
        failure = RuntimeError("synthetic_destination_close_failure_before_release")
        with patch.object(lab.destination, "close", side_effect=failure):
            with self.assertRaises(RuntimeError) as observed:
                lab.__exit__()
        self.assertIs(observed.exception, failure)
        self.assert_closed(lab.store.db)
        # A deliberately failing destination close cannot promise its own release.
        # The retained handle is explicitly cleaned by this test's registered cleanup.
        self.assertEqual(lab.destination.db.execute("SELECT 1").fetchone()[0], 1)

    def test_successful_store_transaction_commit_rollback_and_context_close_are_preserved(self):
        path = self.directory / "store.sqlite"
        with patch("sqlite3.connect", self.tracked_connect):
            with Store(path) as store:
                with store.transaction():
                    store.db.execute("CREATE TABLE ownership_probe (value INTEGER)")
                    store.db.execute("INSERT INTO ownership_probe VALUES (1)")
                with self.assertRaisesRegex(RuntimeError, "synthetic_rollback"):
                    with store.transaction():
                        store.db.execute("INSERT INTO ownership_probe VALUES (2)")
                        raise RuntimeError("synthetic_rollback")
                self.assertEqual(store.db.execute("SELECT value FROM ownership_probe").fetchall()[0][0], 1)
        self.assert_all_closed(1)
        connection = self.tracked_connect(path)
        try:
            self.assertEqual(connection.execute("SELECT value FROM ownership_probe").fetchall(), [(1,)])
        finally:
            connection.close()

    def test_environment_capability_connections_are_closed_without_changing_results(self):
        main = runpy.run_path(str(ROOT / "scripts/check_environment.py"))["main"]
        output = io.StringIO()
        with patch("sqlite3.connect", self.tracked_connect), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn('"result": "pass"', output.getvalue())
        self.assert_all_closed(2)

    def test_environment_sql_failure_closes_handle_before_reporting_failure(self):
        main = runpy.run_path(str(ROOT / "scripts/check_environment.py"))["main"]
        output = io.StringIO()
        with patch("sqlite3.connect", self.deny_sql(sqlite3.SQLITE_CREATE_VTABLE)), redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertIn("DatabaseError", output.getvalue())
        self.assert_all_closed(1)

    def test_backup_restore_test_explicitly_closes_its_connection(self):
        from tests.test_core import CoreTests
        result = unittest.TestResult()
        with patch("sqlite3.connect", self.tracked_connect):
            CoreTests("test_backup_restore_preserves_checkpoint_receipt_and_revocation").run(result)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assert_all_closed(3)

    def test_recovery_setup_failure_runs_registered_cleanup_before_test_run_returns(self):
        from tests.test_round1_recovery import ReceiptRecoveryTests
        for method in ["approve", "enqueue"]:
            with self.subTest(method=method):
                self.handles.clear()
                result = unittest.TestResult()
                with patch("sqlite3.connect", self.tracked_connect), patch.object(ReliabilityLab, method, side_effect=Rejected("synthetic_setup_failure")):
                    ReceiptRecoveryTests("test_expired_committed_recovery_after_reopen_never_delivers").run(result)
                self.assertEqual(len(result.errors), 1)
                self.assertIn("synthetic_setup_failure", result.errors[0][1])
                try:
                    self.assert_all_closed(2)
                finally:
                    self.close_retained_handles()

    def test_embedded_recovery_process_code_closes_on_reconcile_or_json_failure(self):
        from tests.test_reliability import ReliabilityTests
        source = textwrap.dedent(inspect.getsource(ReliabilityTests.test_timeout_after_destination_commit_reconciles_from_a_new_process))
        assignment = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "code" for target in node.targets))
        code = ast.literal_eval(assignment.value)
        for result in [Rejected("synthetic_reconcile_failure"), {"not_json_serializable"}]:
            with self.subTest(failure_type=type(result).__name__):
                self.handles.clear()
                args = ["embedded-recovery-probe", str(self.directory / "source.sqlite"), str(self.directory / "destination.sqlite")]
                options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with patch("sqlite3.connect", self.tracked_connect), patch.object(sys, "argv", args), patch.object(ReliabilityLab, "reconcile", **options), redirect_stdout(io.StringIO()):
                    with self.assertRaises((Rejected, TypeError)):
                        exec(compile(code, "embedded_recovery_process", "exec"), {})
                try:
                    self.assert_all_closed(2)
                finally:
                    self.close_retained_handles()
