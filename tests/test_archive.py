import os
import sqlite3
import tempfile
import unittest
from archive import connect
from examples import two_state, observation_batch
from runtime_models.registry import register_model, resolve_model
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest as W
from analysis_tasks.service import freeze, analyze
from run_reports.reader import read_report, ReportNotPublished
from run_reports.publication import PublicationError
from tests.oracle import enumerate_paths, assert_report

class TestArchive(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="runtime-archive-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "archive.sqlite3")

    def test_model_roundtrip(self):
        model = two_state()
        connection = connect(self.path)
        try:
            ref = register_model(connection, "m", model)
        finally:
            connection.close()
        connection = connect(self.path)
        try:
            recovered = resolve_model(connection, ref)
            self.assertEqual(recovered.definition.states, ("idle", "run"))
            self.assertEqual(register_model(connection, "m", model), ref)
        finally:
            connection.close()

    def test_frozen_reopen(self):
        model, windows = two_state(), [W(0, 2), W(1, 3)]
        connection = connect(self.path)
        try:
            ref = register_model(connection, "m", model)
            original = revise_observations(connection, "s", observation_batch("aba"))
            freeze(connection, "old", ref, original, 3, windows)
            freeze(connection, "published", ref, original, 3, windows)
            published = analyze(connection, "published")
            revised = revise_observations(connection, "s", observation_batch("bbb", 2))
            freeze(connection, "new", ref, revised, 3, windows)
        finally:
            connection.close()
        connection = connect(self.path)
        try:
            old, new = analyze(connection, "old"), analyze(connection, "new")
            assert_report(self, old, enumerate_paths(model, "aba", windows))
            assert_report(self, new, enumerate_paths(model, "bbb", windows))
            self.assertNotEqual(old["mean"], new["mean"])
            self.assertEqual(read_report(connection, "published"), published)
            old["mean"][0] = 999
            old["receipt"]["receipt_id"] = "changed"
            clean = read_report(connection, "old")
            self.assertNotEqual(clean["mean"][0], 999)
            self.assertNotEqual(clean["receipt"]["receipt_id"], "changed")
            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table in {
                        "model_revisions", "observation_history", "observation_current",
                        "sequence_versions", "observation_snapshots"}:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            self.assertEqual(read_report(connection, "old"), clean)
            self.assertEqual(analyze(connection, "old"), clean)
            connection.set_authorizer(None)
        finally:
            connection.close()

    def test_publication_retry(self):
        connection = connect(self.path)
        model = two_state()
        try:
            ref = register_model(connection, "m", model)
            seq = revise_observations(connection, "s", observation_batch("aba"))
            freeze(connection, "retry", ref, seq, 3, [W(0, 3)])
            def fail_before_commit():
                observer = sqlite3.connect(self.path, isolation_level=None)
                try:
                    self.assertEqual(observer.execute(
                        "SELECT count(*) FROM run_reports").fetchone()[0], 0)
                    self.assertEqual(observer.execute(
                        "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
                finally:
                    observer.close()
                raise RuntimeError("controlled precommit failure")
            with self.assertRaises(PublicationError):
                analyze(connection, "retry", before_commit=fail_before_commit)
            with self.assertRaises(ReportNotPublished):
                read_report(connection, "retry")
        finally:
            connection.close()
        connection = connect(self.path)
        try:
            for table in ("run_reports", "publication_receipts"):
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM " + table).fetchone()[0], 0)
            self.assertIsNone(connection.execute(
                "SELECT receipt_id FROM analysis_tasks WHERE task_id='retry'").fetchone()[0])
            with self.assertRaises(ReportNotPublished):
                read_report(connection, "retry")
            report = analyze(connection, "retry")
            assert_report(self, report, enumerate_paths(model, "aba", [W(0, 3)]))
            self.assertEqual(analyze(connection, "retry"), report)
            self.assertEqual(read_report(connection, "retry"), report)
            for table in ("run_reports", "publication_receipts"):
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM " + table).fetchone()[0], 1)
        finally:
            connection.close()
