from runtime_models.schema import ModelDefinition
from observations.records import ObservationRecord

def single_state():
    return ModelDefinition(["run"], [[1]], [[(2, 1)]], [[("x", 1)]])

def two_state():
    return ModelDefinition(
        ["idle", "run"], [[0.25, 0.75], [0.5, 0.5]],
        [[(1, 0.25), (3, 0.75)], [(1, 0.5), (2, 0.5)]],
        [[("a", 0.8), ("b", 0.2)], [("a", 0.25), ("b", 0.75)]])

def observation_batch(symbols, revision=1):
    return [ObservationRecord("sample-" + str(i), revision, 100 + 10 * i, symbol)
            for i, symbol in enumerate(symbols)]
