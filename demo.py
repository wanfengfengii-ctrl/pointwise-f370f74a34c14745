import json
import os
import tempfile
from archive import connect
from examples import two_state, observation_batch
from group_examples import constant_model, observations
from runtime_models.registry import register_model, register_group
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest as W
from analysis_tasks.service import freeze, analyze, freeze_group, analyze_group
from run_reports.reader import (read_report, read_group_report, ReportNotPublished)
from run_reports.publication import PublicationError

def single_device_demo(directory):
    path = os.path.join(directory, "archive.sqlite3")
    connection = connect(path)
    try:
        ref = register_model(connection, "machine-v1", two_state())
        old = revise_observations(connection, "machine", observation_batch("abba"))
        windows = [W(0, 3), W(1, 4)]
        freeze(connection, "frozen-before-correction", ref, old, 4, windows)
        new = revise_observations(connection, "machine", observation_batch("bbbb", 2))
        freeze(connection, "after-correction", ref, new, 4, windows)
        def fail():
            raise RuntimeError("demo controlled precommit failure")
        try:
            analyze(connection, "frozen-before-correction", before_commit=fail)
        except PublicationError:
            try:
                read_report(connection, "frozen-before-correction")
            except ReportNotPublished:
                print("Publication rolled back; frozen task remains retryable.")
    finally:
        connection.close()
    connection = connect(path)
    try:
        for task in ("frozen-before-correction", "after-correction"):
            report = analyze(connection, task)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            if read_report(connection, task) != report:
                raise AssertionError("archived report changed")
    finally:
        connection.close()

def group_demo(directory):
    path = os.path.join(directory, "group-archive.sqlite3")
    connection = connect(path)
    try:
        model = register_model(connection, "constant-v1", constant_model())
        seq_a = revise_observations(connection, "device-a", observations("xx"))
        seq_b = revise_observations(connection, "device-b", observations("xx"))
        devices = [("A", model), ("B", model)]
        shared = register_group(connection, "shared-shocks", devices, (0.5, 0, 0, 0.5))
        independent = register_group(connection, "independent-shocks", devices,
                                     (0.25,) * 4)
        windows = [W(0, 2)]
        freeze_group(connection, "shared", shared, [seq_a, seq_b], 2, windows)
        freeze_group(connection, "independent", independent, [seq_a, seq_b], 2, windows)
        shared_report = analyze_group(connection, "shared")
        independent_report = analyze_group(connection, "independent")
        shared_cross = shared_report["covariance"][1][3]
        independent_cross = independent_report["covariance"][1][3]
        print(json.dumps({"shared_shock_cross_covariance": shared_cross,
                          "independent_shock_cross_covariance": independent_cross},
                         sort_keys=True))
        if not (abs(shared_cross - 2 / 9) < 1e-8 and abs(independent_cross) < 1e-8):
            raise AssertionError("unexpected cross-device covariance")
        freeze_group(connection, "frozen-before-correction", shared, [seq_a, seq_b],
                     2, windows)
        def fail():
            raise RuntimeError("demo controlled precommit failure")
        try:
            analyze_group(connection, "frozen-before-correction", before_commit=fail)
        except PublicationError:
            try:
                read_group_report(connection, "frozen-before-correction")
            except ReportNotPublished:
                print("Group publication rolled back; frozen task remains retryable.")
        for table in ("run_reports", "publication_receipts"):
            count = connection.execute(
                "SELECT count(*) FROM " + table
                + " WHERE task_id='frozen-before-correction'").fetchone()[0]
            if count:
                raise AssertionError("half-published group report left behind")
        new_a = revise_observations(connection, "device-a", observations("xx", 2))
        freeze_group(connection, "after-correction", shared, [new_a, seq_b], 2, windows)
    finally:
        connection.close()
    connection = connect(path)
    try:
        for task in ("shared", "independent", "frozen-before-correction",
                     "after-correction"):
            report = analyze_group(connection, task)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            if read_group_report(connection, task) != report:
                raise AssertionError("archived group report changed")
        old = read_group_report(connection, "frozen-before-correction")
        new = read_group_report(connection, "after-correction")
        if old["devices"][0]["sequence_ref"] != ["device-a", 1]:
            raise AssertionError("old group task lost its frozen version")
        if new["devices"][0]["sequence_ref"] != ["device-a", 2]:
            raise AssertionError("new group task did not use the corrected version")
        if old["devices"][1]["sequence_ref"] != ["device-b", 1]:
            raise AssertionError("uncorrected device sequence changed")
        print("Group reopen: old task kept version 1, new task uses version 2.")
    finally:
        connection.close()

def main():
    with tempfile.TemporaryDirectory(prefix="runtime-archive-demo-") as directory:
        single_device_demo(directory)
        group_demo(directory)

if __name__ == "__main__":
    main()
