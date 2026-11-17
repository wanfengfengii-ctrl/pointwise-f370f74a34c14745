import unittest
from archive import connect
from examples import single_state, two_state, observation_batch
from runtime_models.schema import ModelDefinition, ModelDefinitionError
from runtime_models.registry import register_model, resolve_model, ModelRevisionConflict
from runtime_models.probabilities import ProbabilityValidationError
from observations.records import ObservationRecord, InvalidObservation
from observations.revisions import RevisionConflict
from observations.sequences import (revise_observations, read_sequence_revision,
                                    SequenceConsistencyError)

class TestPreparation(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self.connection.close)

    def test_register_and_revise(self):
        source = single_state()
        ref = register_model(self.connection, "m1", source)
        source.states[0] = "changed"
        self.assertEqual(resolve_model(self.connection, ref).definition.states, ("run",))
        self.assertEqual(register_model(self.connection, "m1", single_state()), ref)
        with self.assertRaises(ModelRevisionConflict):
            register_model(self.connection, "m1", two_state())
        first = revise_observations(self.connection, "s", observation_batch("xx", 2))
        tenth = revise_observations(self.connection, "s", observation_batch("xy", 10))
        self.assertEqual(tenth.version, first.version + 1)
        stale = revise_observations(self.connection, "s", observation_batch("xx", 2))
        self.assertEqual(stale, tenth)
        self.assertEqual(revise_observations(
            self.connection, "s", observation_batch("xy", 10)), tenth)
        self.assertEqual(read_sequence_revision(self.connection, first)[1].symbol, "x")
        self.assertEqual(read_sequence_revision(self.connection, tenth)[1].source_revision, 10)
        self.assertEqual(read_sequence_revision(self.connection, tenth)[1].symbol, "y")

    def test_invalid_probability(self):
        ref = register_model(self.connection, "m", single_state())
        cases = [
            ModelDefinition(["s"], [[0.9]], [[(2, 1)]], [[("x", 1)]]),
            ModelDefinition(["s"], [[1]], [[(0, 1)]], [[("x", 1)]]),
            ModelDefinition(["s"], [[1]], [[(2, -1), (3, 2)]], [[("x", 1)]]),
            ModelDefinition(["s"], [[float("nan")]], [[(1, 1)]], [[("x", 1)]]),
            ModelDefinition(["s", "t"], [[1, 0], [0, 1]],
                            [[(1, 1)], [(1, 1)]], [[("x", 1)], [("x", 1)]])]
        for model in cases:
            with self.subTest(model=model), self.assertRaises(ModelDefinitionError):
                register_model(self.connection, "bad", model)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM model_revisions").fetchone()[0], 1)
        self.assertEqual(resolve_model(self.connection, ref).definition.states, ("run",))
        periodic = ModelDefinition(["s", "t"], [[0, 1], [1, 0]],
                                  [[(1, 1)], [(1, 1)]], [[("x", 1)], [("x", 1)]])
        self.assertIsNotNone(register_model(self.connection, "periodic", periodic))
        tiny = ModelDefinition(["s", "t"], [[1, 1e-250], [1e-250, 1]],
                              [[(1, 1)], [(1, 1)]], [[("x", 1)], [("x", 1)]])
        self.assertIsNotNone(register_model(self.connection, "slow", tiny))

    def test_revision_conflict(self):
        original = revise_observations(self.connection, "s", observation_batch("ab"))
        before = tuple(self.connection.iterdump())
        with self.assertRaises(RevisionConflict):
            revise_observations(self.connection, "s", [
                ObservationRecord("sample-0", 2, 100, "b"),
                ObservationRecord("sample-1", 1, 110, "a")])
        self.assertEqual(tuple(self.connection.iterdump()), before)
        self.assertEqual(read_sequence_revision(self.connection, original)[0].symbol, "a")
        with self.assertRaises(RevisionConflict):
            revise_observations(self.connection, "s", [
                ObservationRecord("new", 2, 200, "a"),
                ObservationRecord("new", 2, 200, "b")])
        with self.assertRaises(InvalidObservation):
            revise_observations(self.connection, "s", [ObservationRecord("old", True, 1, "x")])
        with self.assertRaises(SequenceConsistencyError):
            revise_observations(self.connection, "s", [ObservationRecord("new", 1, 100, "a")])
        self.assertEqual(tuple(self.connection.iterdump()), before)

    def test_stale_history_conflict(self):
        revise_observations(self.connection, "s", observation_batch("a", 10))
        revise_observations(self.connection, "s", observation_batch("b", 2))
        with self.assertRaises(RevisionConflict):
            revise_observations(self.connection, "s", observation_batch("a", 2))
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM sequence_versions").fetchone()[0], 1)
