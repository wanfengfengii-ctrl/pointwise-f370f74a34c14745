from dataclasses import replace
from decimal import Decimal
import unittest
from archive import connect
from examples import two_state, observation_batch
from runtime_models.registry import register_model, resolve_model
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest as W
from analysis_tasks.service import freeze, analyze
from analysis_tasks.bindings import binding_fingerprint
from duration_inference.evidence import compute_evidence
from duration_inference.moments import compute_conditional_moments
from run_reports.windows import build_window_layout, compile_reward_plan
from run_reports.joint import assemble_joint_report
from run_reports.validation import (ReportValidationError, validate_joint_statistics,
                                    validate_occupancy_conservation)
from run_reports.reader import read_report, ArchiveIntegrityError

class TestReportValidation(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self.connection.close)
        ref = register_model(self.connection, "m", two_state())
        seq = revise_observations(self.connection, "s", observation_batch("aba"))
        self.binding = freeze(self.connection, "t", ref, seq, 3, [W(0, 3), W(1, 3)])
        self.layout = build_window_layout(self.binding.states, self.binding.windows)
        self.plan = compile_reward_plan(self.binding, self.layout)
        self.trace = compute_evidence(resolve_model(self.connection, ref).definition,
                                      "aba", binding_fingerprint(self.binding))
        self.moments = compute_conditional_moments(self.trace, self.plan)

    def test_report_integrity(self):
        good = assemble_joint_report(self.binding, self.layout, self.moments)
        self.assertEqual(good.body["input_id"], binding_fingerprint(self.binding))
        cases = [replace(self.moments, input_id="wrong"),
                 replace(self.moments, states=tuple(reversed(self.moments.states))),
                 replace(self.moments, dimensions=tuple(reversed(self.moments.dimensions))),
                 replace(self.moments, second=self.moments.second[:-1]),
                 replace(self.moments, mean=(Decimal("NaN"),) + self.moments.mean[1:])]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ReportValidationError):
                assemble_joint_report(self.binding, self.layout, bad)
        with self.assertRaises(ValueError):
            compute_conditional_moments(self.trace, replace(self.plan, input_id="other"))
        mean, covariance = good.body["mean"], good.body["covariance"]
        bad_mean = list(mean)
        bad_mean[0] += 1
        with self.assertRaises(ReportValidationError):
            validate_occupancy_conservation(self.binding, bad_mean, covariance)
        bad_covariance = [row[:] for row in covariance]
        bad_covariance[0][0] = -1
        with self.assertRaises(ReportValidationError):
            validate_joint_statistics(mean, bad_covariance)
        bad_covariance = [row[:] for row in covariance]
        bad_covariance[0][1] += 1
        with self.assertRaises(ReportValidationError):
            validate_joint_statistics(mean, bad_covariance)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM run_reports").fetchone()[0], 0)

    def test_corrupt_archive_rejected(self):
        analyze(self.connection, "t")
        self.connection.execute("DELETE FROM publication_receipts WHERE task_id='t'")
        with self.assertRaises(ArchiveIntegrityError):
            read_report(self.connection, "t")
        with self.assertRaises(ArchiveIntegrityError):
            analyze(self.connection, "t")

    def test_decimal_cancellation(self):
        from duration_inference.moments import ConditionalMoments
        from duration_inference.evidence import EvidenceValue
        from run_reports.joint import covariance_from_moments
        value = Decimal(10**12)
        moments = ConditionalMoments("i", (), (("d",),), EvidenceValue("1", 0, 0, 1),
                                     (value,), ((value * value + Decimal("0.25"),),))
        self.assertEqual(covariance_from_moments(moments), [[0.25]])

    def test_publication_rollback_memory(self):
        from run_reports.publication import PublicationError
        from run_reports.reader import ReportNotPublished
        def fail():
            raise RuntimeError("controlled precommit failure")
        with self.assertRaises(PublicationError):
            analyze(self.connection, "t", before_commit=fail)
        with self.assertRaises(ReportNotPublished):
            read_report(self.connection, "t")
        for table in ("run_reports", "publication_receipts"):
            self.assertEqual(self.connection.execute(
                "SELECT count(*) FROM " + table).fetchone()[0], 0)
        self.assertIsNone(self.connection.execute(
            "SELECT receipt_id FROM analysis_tasks WHERE task_id='t'").fetchone()[0])
        report = analyze(self.connection, "t")
        self.assertEqual(read_report(self.connection, "t"), report)
        self.assertEqual(analyze(self.connection, "t"), report)
