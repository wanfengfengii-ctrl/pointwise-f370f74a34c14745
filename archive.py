import sqlite3
from contextlib import contextmanager
from itertools import count

_savepoints = count()

@contextmanager
def atomic(connection):
    name = "archive_" + str(next(_savepoints))
    connection.execute("SAVEPOINT " + name)
    try:
        yield connection
        connection.execute("RELEASE " + name)
    except BaseException:
        connection.execute("ROLLBACK TO " + name)
        connection.execute("RELEASE " + name)
        raise

def connect(path=":memory:"):
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    from runtime_models.storage import ModelStore, GroupStore
    from observations.storage import ObservationStore
    from analysis_tasks.storage import TaskStore
    from run_reports.publication import initialize_report_archive
    try:
        with atomic(connection):
            ModelStore(connection).initialize()
            GroupStore(connection).initialize()
            ObservationStore(connection).initialize()
            TaskStore(connection).initialize()
            initialize_report_archive(connection)
        return connection
    except BaseException:
        connection.close()
        raise
