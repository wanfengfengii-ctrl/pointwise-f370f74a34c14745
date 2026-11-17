import math
import unittest
from archive import connect
from examples import single_state, two_state, observation_batch
from runtime_models.schema import ModelDefinition, ModelRef
from runtime_models.registry import register_model, UnknownModelReference
from observations.sequences import revise_observations, SequenceRevision
from analysis_tasks.requests import WindowRequest as W, InvalidTaskRequest
from analysis_tasks.catalog import TaskIdConflict, UnknownTask
from analysis_tasks.service import freeze, analyze
from duration_inference.evidence import ZeroEvidenceError
from run_reports.reader import read_report, ReportNotPublished
from tests.oracle import enumerate_paths, assert_report

class TestDurationAnalysis(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self.connection.close)

    def prepare(self, model, symbols, windows, task="task"):
        ref = register_model(self.connection, "model-" + task, model)
        sequence = revise_observations(self.connection, "sequence-" + task,
                                       observation_batch(symbols))
        binding = freeze(self.connection, task, ref, sequence, len(symbols), windows)
        return binding, analyze(self.connection, task)

    def test_equilibrium_phase(self):
        _, report = self.prepare(single_state(), "xx", [W(0, 2)])
        self.assertEqual(report["mean"][0], 2)
        self.assertAlmostEqual(report["mean"][1], 0.5, delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
        self.assertAlmostEqual(report["covariance"][1][1], 0.25, delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
        self.assertEqual(report["covariance"][0], [0, 0])

    def test_joint_windows(self):
        model = two_state()
        windows = [W(0, 3), W(1, 4), W(1, 4), W(0, 1), W(1, 2), W(2, 3),
                   W(3, 4), W(0, 0), W(4, 4)]
        _, report = self.prepare(model, "abba", windows)
        assert_report(self, report, enumerate_paths(model, "abba", windows))
        self.assertGreater(abs(report["covariance"][5][8]), 1e-5)
        self.assertAlmostEqual(report["covariance"][5][8], report["covariance"][5][5],
                               delta=1e-8)
        for symbols in ("a", "ab", "bba", "aaab", "bbabb"):
            with self.subTest(symbols=symbols):
                local = [W(0, len(symbols)), W(0, min(2, len(symbols)))]
                _, actual = self.prepare(model, symbols, local, "case-" + symbols)
                assert_report(self, actual, enumerate_paths(model, symbols, local))

    def test_full_conditioning(self):
        model, windows = two_state(), [W(0, 1)]
        _, first = self.prepare(model, "aa", windows, "aa")
        _, second = self.prepare(model, "ab", windows, "ab")
        assert_report(self, first, enumerate_paths(model, "aa", windows))
        assert_report(self, second, enumerate_paths(model, "ab", windows))
        self.assertGreater(abs(first["mean"][0] - second["mean"][0]), 0.01)

    def test_evidence_boundary(self):
        model = single_state()
        ref = register_model(self.connection, "zero", model)
        seq = revise_observations(self.connection, "zero", observation_batch("z"))
        freeze(self.connection, "zero", ref, seq, 1, [W(0, 1)])
        with self.assertRaises(ZeroEvidenceError):
            analyze(self.connection, "zero")
        with self.assertRaises(ReportNotPublished):
            read_report(self.connection, "zero")
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
        tiny = ModelDefinition(["s"], [[1]], [[(2, 1)]], [[("x", 1e-250), ("z", 1)]])
        _, positive = self.prepare(tiny, "xxxx", [W(0, 4)], "tiny")
        self.assertIsNone(positive["evidence"]["probability"])
        self.assertFalse(positive["evidence"]["probability_representable"])
        self.assertAlmostEqual(positive["evidence"]["log_evidence"],
                               4 * math.log(1e-250), delta=1e-8)
        self.assertEqual(positive["mean"], [4, 1.5])
        self.assertAlmostEqual(positive["covariance"][1][1], 0.25, delta=1e-8)
        self.assertEqual(positive["evidence"]["exponent"], -1000)

    def test_freeze_binding(self):
        model = register_model(self.connection, "m", single_state())
        seq = revise_observations(self.connection, "s", observation_batch("xxx"))
        first = freeze(self.connection, "t", model, seq, 2, [W(1, 2), W(0, 2), W(1, 2)])
        self.assertEqual(first, freeze(
            self.connection, "t", model, seq, 2, [W(1, 2), W(0, 2), W(1, 2)]))
        with self.assertRaises(TaskIdConflict):
            freeze(self.connection, "t", model, seq, 3, [W(0, 3)])
        for prefix, windows in [(4, []), (True, []), (2, [W(0, 3)]), (2, [W(2, 1)]),
                                (2, [W(False, 1)])]:
            with self.subTest(prefix=prefix, windows=windows):
                with self.assertRaises(InvalidTaskRequest):
                    freeze(self.connection, "invalid", model, seq, prefix, windows)
        with self.assertRaises(UnknownModelReference):
            freeze(self.connection, "u", ModelRef("m", "wrong"), seq, 1, [])
        with self.assertRaises(LookupError):
            freeze(self.connection, "u", model, SequenceRevision("s", 99), 1, [])
        with self.assertRaises(UnknownTask):
            analyze(self.connection, "missing")
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM analysis_tasks").fetchone()[0], 1)

    def test_empty_inputs(self):
        _, report = self.prepare(single_state(), "", [W(0, 0), W(0, 0)], "empty")
        self.assertEqual(report["mean"], [0, 0, 0, 0])
        self.assertEqual(report["covariance"], [[0] * 4 for _ in range(4)])
        self.assertEqual(report["evidence"]["probability"], 1)
        _, no_windows = self.prepare(two_state(), "aba", [], "no-windows")
        self.assertEqual(no_windows["mean"], [])
        self.assertEqual(no_windows["covariance"], [])
        assert_report(self, no_windows, enumerate_paths(two_state(), "aba", []))
