import math
import os
import tempfile
import unittest
from fractions import Fraction
from archive import connect
from examples import observation_batch
from group_examples import constant_model, informative_case, observations
from runtime_models.schema import ModelDefinition, ModelRef, GroupRef, ModelDefinitionError
from runtime_models.registry import (register_model, register_group, ModelRevisionConflict,
                                     UnknownModelReference, UnknownGroupReference)
from runtime_models.probabilities import ProbabilityValidationError
from runtime_models.stationary import StationaryDistributionError
from observations.records import ObservationRecord
from observations.sequences import revise_observations, SequenceRevision
from analysis_tasks.requests import WindowRequest as W, InvalidTaskRequest
from analysis_tasks.catalog import TaskIdConflict, UnknownTask
from analysis_tasks.service import freeze, analyze, freeze_group, analyze_group
from duration_inference.evidence import ZeroEvidenceError
from run_reports.reader import (read_report, read_group_report, ReportNotPublished,
                                ArchiveIntegrityError)
from run_reports.publication import PublicationError
from tests.group_oracle import enumerate_group_paths, assert_group_report


def timed_records(symbols, start=100, step=10, revision=1):
    return [ObservationRecord("sample-" + str(i), revision, start + step * i, symbol)
            for i, symbol in enumerate(symbols)]


class TestGroupAnalysis(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self.connection.close)

    def prepare_constant(self, shock_probs, task="task", windows=(W(0, 2),), prefix=2):
        model = register_model(self.connection, "constant-" + task, constant_model())
        refs = [revise_observations(self.connection, name + "-" + task, observations("xx"))
                for name in ("A", "B")]
        group = register_group(self.connection, "group-" + task,
                               [("A", model), ("B", model)], shock_probs)
        binding = freeze_group(self.connection, task, group, refs, prefix, list(windows))
        return binding, group, model, refs

    def test_shared_and_independent_analytic(self):
        cases = [((0.5, 0, 0, 0.5), Fraction(2, 9)),
                 ((0.25, 0.25, 0.25, 0.25), Fraction(0))]
        for shock_probs, cross in cases:
            with self.subTest(shock_probs=shock_probs):
                task = "case-" + str(abs(hash(shock_probs)))
                self.prepare_constant(shock_probs, task)
                report = analyze_group(self.connection, task)
                self.assertEqual(report["dimensions"],
                                 [[0, "A", "occupancy", "run"], [0, "A", "renewals", ""],
                                  [0, "B", "occupancy", "run"], [0, "B", "renewals", ""]])
                for actual, expected in zip(report["mean"], [2, Fraction(2, 3), 2,
                                                             Fraction(2, 3)]):
                    self.assertAlmostEqual(actual, float(expected), delta=1e-8,
                                           msg="RENEWAL_MOMENT_MISMATCH")
                self.assertAlmostEqual(report["covariance"][1][1], 2 / 9, delta=1e-8,
                                       msg="RENEWAL_MOMENT_MISMATCH")
                self.assertAlmostEqual(report["covariance"][3][3], 2 / 9, delta=1e-8,
                                       msg="RENEWAL_MOMENT_MISMATCH")
                self.assertAlmostEqual(report["covariance"][1][3], float(cross), delta=1e-8,
                                       msg="RENEWAL_MOMENT_MISMATCH")
                self.assertAlmostEqual(report["covariance"][3][1], float(cross), delta=1e-8,
                                       msg="RENEWAL_MOMENT_MISMATCH")
                self.assertEqual(report["evidence"]["probability"], 1.0)
                oracle = enumerate_group_paths(
                    (constant_model(), constant_model()), shock_probs,
                    ("xx", "xx"), [W(0, 2)])
                assert_group_report(self, report, oracle)
                self.assertEqual(analyze_group(self.connection, task), report)
                self.assertEqual(read_group_report(self.connection, task), report)

    def test_informative_case(self):
        sample = informative_case()
        models = sample["models"]
        refs = [register_model(self.connection, "informative-" + str(i), model)
                for i, model in enumerate(models)]
        sequences = [revise_observations(self.connection, name, observations(symbols))
                     for name, symbols in zip(("A", "B"), sample["symbols"])]
        group = register_group(self.connection, "informative",
                               [("A", refs[0]), ("B", refs[1])], sample["shock_probs"])
        windows = list(sample["windows"])
        freeze_group(self.connection, "informative", group, sequences,
                     sample["prefix"], windows)
        report = analyze_group(self.connection, "informative")
        oracle = enumerate_group_paths(models, sample["shock_probs"], sample["symbols"],
                                       sample["windows"])
        assert_group_report(self, report, oracle)
        self.assertNotEqual(report["covariance"][2][5], 0)

    def test_duplicate_windows(self):
        sample = informative_case()
        models = sample["models"]
        refs = [register_model(self.connection, "dup-" + str(i), model)
                for i, model in enumerate(models)]
        sequences = [revise_observations(self.connection, name, observations(symbols))
                     for name, symbols in zip(("A", "B"), sample["symbols"])]
        group = register_group(self.connection, "dup", [("A", refs[0]), ("B", refs[1])],
                               sample["shock_probs"])
        windows = [W(0, 2), W(0, 2)]
        freeze_group(self.connection, "dup", group, sequences, 3, windows)
        report = analyze_group(self.connection, "dup")
        oracle = enumerate_group_paths(models, sample["shock_probs"], sample["symbols"],
                                       tuple(windows))
        assert_group_report(self, report, oracle)
        block = len(report["mean"]) // 2
        for i in range(block):
            self.assertAlmostEqual(report["mean"][i], report["mean"][block + i],
                                   delta=1e-8)
        for i in range(2 * block):
            for j in range(block):
                self.assertAlmostEqual(report["covariance"][i][j],
                                       report["covariance"][i][block + j],
                                       delta=1e-8, msg="RENEWAL_MOMENT_MISMATCH")

    def test_same_state_renewal_mixed_durations(self):
        model = ModelDefinition(["run"], [[1]], [[(1, 0.5), (2, 0.5)]], [[("x", 1)]])
        ref = register_model(self.connection, "mixed", model)
        sequences = [revise_observations(self.connection, name, observations("xxx"))
                     for name in ("A", "B")]
        group = register_group(self.connection, "mixed", [("A", ref), ("B", ref)],
                               (0.5, 0, 0, 0.5))
        windows = [W(0, 3), W(1, 3)]
        freeze_group(self.connection, "mixed", group, sequences, 3, windows)
        report = analyze_group(self.connection, "mixed")
        oracle = enumerate_group_paths((model, model), (0.5, 0, 0, 0.5),
                                       ("xxx", "xxx"), tuple(windows))
        assert_group_report(self, report, oracle)
        self.assertGreater(report["mean"][1], 0)

    def test_empty_prefix(self):
        model = register_model(self.connection, "empty", constant_model())
        refs = [revise_observations(self.connection, name, observations("xx"))
                for name in ("A", "B")]
        group = register_group(self.connection, "empty", [("A", model), ("B", model)],
                               (0.5, 0, 0, 0.5))
        freeze_group(self.connection, "empty-zero", group, refs, 0, [W(0, 0)])
        report = analyze_group(self.connection, "empty-zero")
        self.assertEqual(report["mean"], [0, 0, 0, 0])
        self.assertEqual(report["covariance"], [[0] * 4 for _ in range(4)])
        self.assertEqual(report["evidence"]["probability"], 1)
        self.assertEqual(report["evidence"]["log_evidence"], 0)
        oracle = enumerate_group_paths((constant_model(), constant_model()),
                                       (0.5, 0, 0, 0.5), ("", ""), (W(0, 0),))
        assert_group_report(self, report, oracle)
        freeze_group(self.connection, "empty-none", group, refs, 0, [])
        bare = analyze_group(self.connection, "empty-none")
        self.assertEqual(bare["mean"], [])
        self.assertEqual(bare["covariance"], [])
        self.assertEqual(bare["evidence"]["probability"], 1)

    def test_zero_and_tiny_evidence(self):
        model = register_model(self.connection, "zero", constant_model())
        refs = [revise_observations(self.connection, name, observations("xz"))
                for name in ("A", "B")]
        group = register_group(self.connection, "zero", [("A", model), ("B", model)],
                               (0.5, 0, 0, 0.5))
        freeze_group(self.connection, "zero", group, refs, 2, [W(0, 2)])
        with self.assertRaises(ZeroEvidenceError):
            analyze_group(self.connection, "zero")
        with self.assertRaises(ReportNotPublished):
            read_group_report(self.connection, "zero")
        freeze_group(self.connection, "zero-bare", group, refs, 2, [])
        with self.assertRaises(ZeroEvidenceError):
            analyze_group(self.connection, "zero-bare")
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
        tiny = ModelDefinition(["s"], [[1]], [[(1, 0.5), (2, 0.5)]],
                               [[("x", 1e-250), ("z", 1)]])
        tiny_ref = register_model(self.connection, "tiny", tiny)
        tiny_refs = [revise_observations(self.connection, name, observations("xx"))
                     for name in ("tA", "tB")]
        tiny_group = register_group(self.connection, "tiny",
                                    [("tA", tiny_ref), ("tB", tiny_ref)], (0.5, 0, 0, 0.5))
        freeze_group(self.connection, "tiny", tiny_group, tiny_refs, 2, [W(0, 2)])
        report = analyze_group(self.connection, "tiny")
        self.assertIsNone(report["evidence"]["probability"])
        self.assertFalse(report["evidence"]["probability_representable"])
        self.assertAlmostEqual(report["evidence"]["log_evidence"],
                               4 * math.log(1e-250), delta=1e-8)
        self.assertEqual(report["evidence"]["exponent"], -1000)
        oracle = enumerate_group_paths((tiny, tiny), (0.5, 0, 0, 0.5), ("xx", "xx"),
                                       (W(0, 2),))
        assert_group_report(self, report, oracle)

    def test_full_conditioning(self):
        sample = informative_case()
        models = sample["models"]
        refs = [register_model(self.connection, "cond-" + str(i), model)
                for i, model in enumerate(models)]
        seq_a = revise_observations(self.connection, "condA", observations("aba"))
        group = register_group(self.connection, "cond", [("A", refs[0]), ("B", refs[1])],
                               sample["shock_probs"])
        reports = []
        for name, symbols_b in (("cond-yxx", "yxx"), ("cond-yyy", "yyy")):
            seq_b = revise_observations(self.connection, name, observations(symbols_b))
            freeze_group(self.connection, name, group, [seq_a, seq_b], 3, [W(0, 3)])
            report = analyze_group(self.connection, name)
            oracle = enumerate_group_paths(models, sample["shock_probs"],
                                           ("aba", symbols_b), (W(0, 3),))
            assert_group_report(self, report, oracle)
            reports.append(report)
        self.assertGreater(abs(reports[0]["mean"][2] - reports[1]["mean"][2]), 0.01)

    def test_prefix_boundaries(self):
        model = register_model(self.connection, "wide", constant_model())
        refs = [revise_observations(self.connection, name,
                                    observation_batch("x" * 34))
                for name in ("wA", "wB")]
        group = register_group(self.connection, "wide", [("A", model), ("B", model)],
                               (0.5, 0, 0, 0.5))
        freeze_group(self.connection, "wide", group, refs, 32, [W(0, 32)])
        report = analyze_group(self.connection, "wide")
        self.assertEqual(report["mean"][0], 32)
        self.assertAlmostEqual(report["mean"][1], 31 * 2 / 3, delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
        self.assertAlmostEqual(report["mean"][3], 31 * 2 / 3, delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
        with self.assertRaises(InvalidTaskRequest):
            freeze_group(self.connection, "too-long", group, refs, 33, [])

    def test_freeze_validation(self):
        model = register_model(self.connection, "fv", constant_model())
        refs = [revise_observations(self.connection, name, observations("xx"))
                for name in ("fvA", "fvB")]
        group = register_group(self.connection, "fv", [("A", model), ("B", model)],
                               (0.5, 0, 0, 0.5))
        binding = freeze_group(self.connection, "fv", group, refs, 2, [W(0, 2)])
        self.assertEqual(binding, freeze_group(self.connection, "fv", group, refs, 2,
                                               [W(0, 2)]))
        with self.assertRaises(TaskIdConflict):
            freeze_group(self.connection, "fv", group, refs, 1, [W(0, 1)])
        bad_windows = [[W(0, 1), W(0, 1), W(0, 1)], [W(0, 3)], [W(1, 0)], [W(False, 1)]]
        for windows in bad_windows:
            with self.subTest(windows=windows), self.assertRaises(InvalidTaskRequest):
                freeze_group(self.connection, "bad-windows", group, refs, 2, windows)
        for prefix in (True, -1, 3):
            with self.subTest(prefix=prefix), self.assertRaises(InvalidTaskRequest):
                freeze_group(self.connection, "bad-prefix", group, refs, prefix, [])
        for sequences in ([refs[0]], [refs[0], refs[1], refs[0]]):
            with self.subTest(sequences=sequences), self.assertRaises(InvalidTaskRequest):
                freeze_group(self.connection, "bad-count", group, sequences, 2, [])
        skewed = revise_observations(self.connection, "fvC",
                                     timed_records("xx", step=15))
        with self.assertRaises(InvalidTaskRequest):
            freeze_group(self.connection, "skewed", group, [refs[0], skewed], 2, [])
        aligned = revise_observations(self.connection, "fvD", timed_records("xx"))
        freeze_group(self.connection, "aligned", group,
                     [refs[0], aligned], 2, [W(0, 2)])
        with self.assertRaises(LookupError):
            freeze_group(self.connection, "unknown-seq", group,
                         [refs[0], SequenceRevision("fvB", 99)], 2, [])
        with self.assertRaises(LookupError):
            freeze_group(self.connection, "unknown-group",
                         GroupRef("fv", "wrong"), refs, 2, [])
        with self.assertRaises(LookupError):
            freeze_group(self.connection, "unknown-group2", GroupRef("missing", "x"),
                         refs, 2, [])
        with self.assertRaises(LookupError):
            freeze_group(self.connection, "not-a-group", "shared", refs, 2, [])
        with self.assertRaises(UnknownTask):
            analyze_group(self.connection, "missing")
        with self.assertRaises(ReportNotPublished):
            read_group_report(self.connection, "fv")

    def test_register_group_validation(self):
        model = register_model(self.connection, "rv", constant_model())
        devices = [("A", model), ("B", model)]
        group = register_group(self.connection, "rv", devices, (0.5, 0, 0, 0.5))
        self.assertEqual(register_group(self.connection, "rv", devices,
                                        (0.5, 0.0, 0.0, 0.5)), group)
        with self.assertRaises(ModelRevisionConflict):
            register_group(self.connection, "rv", devices, (0.25,) * 4)
        with self.assertRaises(StationaryDistributionError):
            register_group(self.connection, "nonunique", devices, (1, 0, 0, 0))
        register_group(self.connection, "nonunique", devices, (0.5, 0, 0, 0.5))
        bad_probs = [(0.9, 0, 0, 0), (1.1, 0, 0, -0.1), (float("nan"), 0, 0, 1),
                     (True, 0, 0, 1), (0.5, 0, 0.5), (0.5, 0, 0, 0.5, 0), "abcd"]
        for probs in bad_probs:
            with self.subTest(probs=probs), self.assertRaises(ModelDefinitionError):
                register_group(self.connection, "bad-probs", devices, probs)
        with self.assertRaises(ProbabilityValidationError):
            register_group(self.connection, "bad-probs2", devices, (0.5, 0.5, 0.5, 0.5))
        bad_devices = [[("A", model)], [("A", model)] * 3,
                       [("A", model), ("A", model)], [("", model), ("B", model)],
                       [("A", model), "B"]]
        for device_models in bad_devices:
            with self.subTest(devices=device_models), \
                    self.assertRaises(ModelDefinitionError):
                register_group(self.connection, "bad-devices", device_models,
                               (0.5, 0, 0, 0.5))
        with self.assertRaises(UnknownModelReference):
            register_group(self.connection, "unknown-model",
                           [("A", ModelRef("rv", "wrong")), ("B", model)],
                           (0.5, 0, 0, 0.5))
        with self.assertRaises(LookupError):
            register_group(self.connection, "not-a-model", [("A", "x"), ("B", model)],
                           (0.5, 0, 0, 0.5))
        three_states = ModelDefinition(
            ["a", "b", "c"], [[0.5, 0.5, 0], [0, 0.5, 0.5], [0.5, 0, 0.5]],
            [[(1, 1)]] * 3, [[("x", 1)]] * 3)
        big = register_model(self.connection, "big", three_states)
        with self.assertRaises(ModelDefinitionError):
            register_group(self.connection, "too-many-states", [("A", big), ("B", model)],
                           (0.5, 0, 0, 0.5))
        long_duration = ModelDefinition(["s"], [[1]], [[(3, 1)]], [[("x", 1)]])
        long_ref = register_model(self.connection, "long", long_duration)
        with self.assertRaises(ModelDefinitionError):
            register_group(self.connection, "too-long-duration",
                           [("A", long_ref), ("B", model)], (0.5, 0, 0, 0.5))
        register_model(self.connection, "shared-name", constant_model())
        self.assertIsNotNone(register_group(self.connection, "shared-name", devices,
                                            (0.5, 0, 0, 0.5)))
        with self.assertRaises(ModelDefinitionError):
            register_group(self.connection, "", devices, (0.5, 0, 0, 0.5))
        unit = ModelDefinition(["s"], [[1]], [[(1, 1)]], [[("x", 1)]])
        unit_ref = register_model(self.connection, "unit", unit)
        periodic = register_group(self.connection, "periodic",
                                  [("A", model), ("B", unit_ref)], (1, 0, 0, 0))
        self.assertIsNotNone(periodic)

    def test_cross_kind_and_namespace(self):
        model = register_model(self.connection, "ck", constant_model())
        refs = [revise_observations(self.connection, name, observations("xx"))
                for name in ("ckA", "ckB")]
        group = register_group(self.connection, "ck", [("A", model), ("B", model)],
                               (0.5, 0, 0, 0.5))
        freeze_group(self.connection, "group-task", group, refs, 2, [W(0, 2)])
        seq = revise_observations(self.connection, "ckS", observation_batch("xx"))
        freeze(self.connection, "single-task", model, seq, 2, [W(0, 2)])
        with self.assertRaises(ValueError):
            analyze(self.connection, "group-task")
        with self.assertRaises(ValueError):
            analyze_group(self.connection, "single-task")
        with self.assertRaises(ValueError):
            read_report(self.connection, "group-task")
        with self.assertRaises(ValueError):
            read_group_report(self.connection, "single-task")
        with self.assertRaises(TaskIdConflict):
            freeze(self.connection, "group-task", model, seq, 2, [W(0, 2)])
        with self.assertRaises(TaskIdConflict):
            freeze_group(self.connection, "single-task", group, refs, 2, [W(0, 2)])
        group_report = analyze_group(self.connection, "group-task")
        single_report = analyze(self.connection, "single-task")
        with self.assertRaises(ValueError):
            read_report(self.connection, "group-task")
        with self.assertRaises(ValueError):
            read_group_report(self.connection, "single-task")
        self.assertEqual(read_group_report(self.connection, "group-task"), group_report)
        self.assertEqual(read_report(self.connection, "single-task"), single_report)

    def test_publication_retry(self):
        self.prepare_constant((0.5, 0, 0, 0.5), "retry")
        calls = []

        def fail():
            calls.append(1)
            raise RuntimeError("controlled precommit failure")

        with self.assertRaises(PublicationError):
            analyze_group(self.connection, "retry", before_commit=fail)
        with self.assertRaises(ReportNotPublished):
            read_group_report(self.connection, "retry")
        for table in ("run_reports", "publication_receipts"):
            self.assertEqual(self.connection.execute(
                "SELECT count(*) FROM " + table).fetchone()[0], 0)
        self.assertIsNone(self.connection.execute(
            "SELECT receipt_id FROM analysis_tasks WHERE task_id='retry'").fetchone()[0])
        report = analyze_group(self.connection, "retry",
                               before_commit=lambda: calls.append(1))
        self.assertEqual(len(calls), 2)
        self.assertEqual(analyze_group(self.connection, "retry"), report)
        self.assertEqual(len(calls), 2)
        self.assertEqual(read_group_report(self.connection, "retry"), report)

    def test_return_mutation_isolation(self):
        self.prepare_constant((0.5, 0, 0, 0.5), "mutate")
        report = analyze_group(self.connection, "mutate")
        report["mean"][1] = 999
        report["devices"][0]["states"].append("bogus")
        report["receipt"]["receipt_id"] = "changed"
        clean = read_group_report(self.connection, "mutate")
        self.assertAlmostEqual(clean["mean"][1], 2 / 3, delta=1e-8)
        self.assertEqual(clean["devices"][0]["states"], ["run"])
        self.assertNotEqual(clean["receipt"]["receipt_id"], "changed")

    def test_corrupt_group_archive_rejected(self):
        self.prepare_constant((0.5, 0, 0, 0.5), "corrupt")
        analyze_group(self.connection, "corrupt")
        self.connection.execute(
            "DELETE FROM publication_receipts WHERE task_id='corrupt'")
        with self.assertRaises(ArchiveIntegrityError):
            read_group_report(self.connection, "corrupt")
        with self.assertRaises(ArchiveIntegrityError):
            analyze_group(self.connection, "corrupt")

    def test_tiny_positive_shock_probability(self):
        model = register_model(self.connection, "tinyshock", constant_model())
        group = register_group(self.connection, "tinyshock",
                               [("A", model), ("B", model)], (1e-250, 0, 0, 1.0))
        refs = [revise_observations(self.connection, name, observations("xx"))
                for name in ("tsA", "tsB")]
        freeze_group(self.connection, "tinyshock", group, refs, 2, [W(0, 2)])
        report = analyze_group(self.connection, "tinyshock")
        oracle = enumerate_group_paths((constant_model(), constant_model()),
                                       (1e-250, 0, 0, 1.0), ("xx", "xx"), (W(0, 2),))
        assert_group_report(self, report, oracle)


class TestGroupArchive(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="runtime-group-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "archive.sqlite3")

    def test_reopen_after_correction(self):
        windows = [W(0, 2)]
        connection = connect(self.path)
        try:
            model = register_model(connection, "m", constant_model())
            old_a = revise_observations(connection, "A", observations("xx"))
            old_b = revise_observations(connection, "B", observations("xx"))
            group = register_group(connection, "g", [("A", model), ("B", model)],
                                   (0.5, 0, 0, 0.5))
            freeze_group(connection, "old", group, [old_a, old_b], 2, windows)
            freeze_group(connection, "published", group, [old_a, old_b], 2, windows)
            published = analyze_group(connection, "published")
            new_a = revise_observations(connection, "A", observations("xx", 2))
            freeze_group(connection, "new", group, [new_a, old_b], 2, windows)

            def fail():
                raise RuntimeError("controlled precommit failure")

            with self.assertRaises(PublicationError):
                analyze_group(connection, "old", before_commit=fail)
            with self.assertRaises(ReportNotPublished):
                read_group_report(connection, "old")
        finally:
            connection.close()
        connection = connect(self.path)
        try:
            for table in ("run_reports", "publication_receipts"):
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM " + table + " WHERE task_id='old'").fetchone()[0],
                    0)
            old = analyze_group(connection, "old")
            oracle = enumerate_group_paths((constant_model(), constant_model()),
                                           (0.5, 0, 0, 0.5), ("xx", "xx"), tuple(windows))
            assert_group_report(self, old, oracle)
            self.assertEqual(old["devices"][0]["sequence_ref"], ["A", 1])
            new = analyze_group(connection, "new")
            self.assertEqual(new["devices"][0]["sequence_ref"], ["A", 2])
            self.assertEqual(new["devices"][1]["sequence_ref"], ["B", 1])
            self.assertNotEqual(old["input_id"], new["input_id"])
            self.assertEqual(read_group_report(connection, "published"), published)
            self.assertEqual(read_group_report(connection, "old"), old)
            old["mean"][1] = 999
            self.assertAlmostEqual(read_group_report(connection, "old")["mean"][1],
                                   2 / 3, delta=1e-8)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
