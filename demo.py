import json
import os
import tempfile
from archive import connect
from examples import two_state, observation_batch
from runtime_models.registry import register_model
from observations.sequences import revise_observations
from analysis_tasks.requests import WindowRequest as W
from analysis_tasks.service import freeze, analyze
from run_reports.reader import read_report, ReportNotPublished
from run_reports.publication import PublicationError

def main():
    with tempfile.TemporaryDirectory(prefix="runtime-archive-demo-") as directory:
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

if __name__ == "__main__":
    main()
