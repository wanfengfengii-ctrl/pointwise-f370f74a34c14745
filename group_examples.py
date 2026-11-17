"""Raw group inputs and analytic checks; no group inference implementation."""
import argparse
import json
import math
from fractions import Fraction
from archive import connect
from runtime_models.schema import ModelDefinition, ModelDefinitionError, canonicalize_model
from runtime_models.probabilities import validate_model_probabilities
from runtime_models.registry import register_model
from observations.records import ObservationRecord
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest
from analysis_tasks.catalog import TaskIdConflict


def observations(symbols, revision=1):
    return [ObservationRecord("sample-" + str(i), revision, 100 + 10 * i, symbol)
            for i, symbol in enumerate(symbols)]


def constant_model():
    return ModelDefinition(["run"], [[1]], [[(2, 1)]], [[("x", 1)]])


def analytic_cases():
    return [
        {"name": "shared", "shock_probs": (0.5, 0, 0, 0.5),
         "renewal_mean": "2/3", "renewal_variance": "2/9",
         "cross_covariance": "2/9"},
        {"name": "independent", "shock_probs": (0.25, 0.25, 0.25, 0.25),
         "renewal_mean": "2/3", "renewal_variance": "2/9",
         "cross_covariance": "0"}
    ]


def informative_case():
    first = ModelDefinition(
        ["idle", "run"], [[0.5, 0.5], [0.25, 0.75]],
        [[(1, 0.5), (2, 0.5)], [(2, 1)]],
        [[("a", 0.75), ("b", 0.25)], [("a", 0.25), ("b", 0.75)]])
    second = ModelDefinition(
        ["cold", "hot"], [[0.75, 0.25], [0.5, 0.5]],
        [[(1, 1)], [(1, 0.5), (2, 0.5)]],
        [[("x", 0.8), ("y", 0.2)], [("x", 0.2), ("y", 0.8)]])
    return {"models": (first, second), "symbols": ("aba", "xyx"),
            "shock_probs": (0.5, 0, 0, 0.5), "prefix": 3,
            "windows": (WindowRequest(0, 2), WindowRequest(1, 3))}


def show_fixtures():
    sample = informative_case()
    for model in (constant_model(), *sample["models"]):
        validate_model_probabilities(canonicalize_model(model))
    payload = {
        "analytic": {"device_ids": ["A", "B"],
                     "models": [constant_model().to_data(), constant_model().to_data()],
                     "records": [[r.to_data() for r in observations("xx")]] * 2,
                     "prefix": 2, "windows": [[0, 2]], "cases": analytic_cases()},
        "informative": {
            "device_ids": ["A", "B"],
            "models": [m.to_data() for m in sample["models"]],
            "records": [[r.to_data() for r in observations(s)] for s in sample["symbols"]],
            "shock_probs": sample["shock_probs"], "prefix": sample["prefix"],
            "windows": [[w.left, w.right] for w in sample["windows"]]},
        "nonunique_stationary": {"shock_probs": [1, 0, 0, 0],
                                 "models": [constant_model().to_data(), constant_model().to_data()]}
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def near(actual, expected):
    if not math.isfinite(actual) or abs(actual - float(Fraction(expected))) > 1e-8:
        raise AssertionError((actual, expected))


def check_analytic():
    from runtime_models.registry import register_group
    from analysis_tasks.service import freeze_group, analyze_group
    from run_reports.reader import read_group_report
    from runtime_models.registry import ModelRevisionConflict
    connection = connect()
    try:
        model = register_model(connection, "constant", constant_model())
        refs = [revise_observations(connection, name, observations("xx"))
                for name in ("A", "B")]
        device_models = [("A", model), ("B", model)]
        for case in analytic_cases():
            name = case["name"]
            group = register_group(connection, name, device_models, case["shock_probs"])
            assert register_group(connection, name, device_models, case["shock_probs"]) == group
            binding = freeze_group(connection, name, group, refs, 2, [WindowRequest(0, 2)])
            assert freeze_group(connection, name, group, refs, 2, [WindowRequest(0, 2)]) == binding
            report = analyze_group(connection, name)
            assert report["dimensions"] == [
                [0, "A", "occupancy", "run"], [0, "A", "renewals", ""],
                [0, "B", "occupancy", "run"], [0, "B", "renewals", ""]]
            assert report["group_ref"] == [group.revision_id, group.digest]
            assert report["prefix"] == 2 and report["windows"] == [[0, 2]]
            assert len(report["mean"]) == len(report["covariance"]) == 4
            for actual, expected in zip(report["mean"], ["2", "2/3", "2", "2/3"]):
                near(actual, expected)
            for i, row in enumerate(report["covariance"]):
                assert len(row) == 4
                for j, value in enumerate(row):
                    expected = ("0" if i in (0, 2) or j in (0, 2)
                                else case["renewal_variance"] if i == j
                                else case["cross_covariance"])
                    near(value, expected)
            near(report["evidence"]["probability"], "1")
            assert len(report["devices"]) == 2
            for device, sequence, device_id in zip(report["devices"], refs, ("A", "B")):
                assert device["device_id"] == device_id
                assert device["model_ref"] == [model.revision_id, model.digest]
                assert device["sequence_ref"] == [sequence.sequence_id, sequence.version]
                assert device["records"] == [r.to_data() for r in observations("xx")]
            assert read_group_report(connection, name) == report
            assert analyze_group(connection, name) == report
            report["mean"][1] = 999
            near(read_group_report(connection, name)["mean"][1], "2/3")
            try:
                freeze_group(connection, name, group, refs, 1, [WindowRequest(0, 1)])
            except TaskIdConflict:
                pass
            else:
                raise AssertionError("different binding accepted")
            print(json.dumps({"case": name, "report": read_group_report(connection, name)},
                             ensure_ascii=False, sort_keys=True))
        try:
            register_group(connection, "nonunique", device_models, (1, 0, 0, 0))
        except ModelDefinitionError:
            pass
        else:
            raise AssertionError("nonunique stationary group accepted")
        register_group(connection, "nonunique", device_models, (0.5, 0, 0, 0.5))
        try:
            register_group(connection, "shared", device_models, (0.25,) * 4)
        except ModelRevisionConflict:
            pass
        else:
            raise AssertionError("group revision replacement accepted")
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_analytic()
    else:
        show_fixtures()


if __name__ == "__main__":
    main()
