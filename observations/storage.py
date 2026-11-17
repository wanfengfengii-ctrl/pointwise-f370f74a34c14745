import json
from archive import atomic
from observations.records import ObservationRecord

class ObservationStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self):
        statements = (
            """CREATE TABLE IF NOT EXISTS observation_history(
                sequence_id TEXT, identity TEXT, revision INTEGER, time INTEGER,
                symbol TEXT, PRIMARY KEY(sequence_id,identity,revision))""",
            """CREATE TABLE IF NOT EXISTS observation_current(
                sequence_id TEXT, identity TEXT, revision INTEGER,
                PRIMARY KEY(sequence_id,identity))""",
            """CREATE TABLE IF NOT EXISTS sequence_versions(
                sequence_id TEXT, version INTEGER, body TEXT NOT NULL,
                PRIMARY KEY(sequence_id,version))""",
            """CREATE TABLE IF NOT EXISTS sequence_heads(
                sequence_id TEXT PRIMARY KEY, version INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS observation_snapshots(
                snapshot_id TEXT PRIMARY KEY, body TEXT NOT NULL)""")
        for statement in statements:
            self.connection.execute(statement)

    def load_revision_state(self, sequence_id):
        rows = self.connection.execute(
            "SELECT identity,revision,time,symbol FROM observation_history WHERE sequence_id=?",
            (sequence_id,)).fetchall()
        history = {(r[0], r[1]): ObservationRecord(*r) for r in rows}
        current = {}
        for identity, revision in self.connection.execute(
                "SELECT identity,revision FROM observation_current WHERE sequence_id=?",
                (sequence_id,)):
            current[identity] = history[(identity, revision)]
        row = self.connection.execute(
            "SELECT version FROM sequence_heads WHERE sequence_id=?", (sequence_id,)).fetchone()
        return current, history, None if row is None else row[0]

    def commit_revision_plan(self, sequence_id, plan, ordered, version):
        for record in plan.received:
            self.connection.execute(
                "INSERT OR IGNORE INTO observation_history VALUES(?,?,?,?,?)",
                (sequence_id, *record.to_data()))
        if not plan.changed and version is not None:
            return version
        next_version = 1 if version is None else version + 1
        for record in ordered:
            self.connection.execute(
                """INSERT INTO observation_current VALUES(?,?,?)
                ON CONFLICT(sequence_id,identity) DO UPDATE SET revision=excluded.revision""",
                (sequence_id, record.identity, record.source_revision))
        body = json.dumps([r.to_data() for r in ordered], separators=(",", ":"))
        self.connection.execute("INSERT INTO sequence_versions VALUES(?,?,?)",
                                (sequence_id, next_version, body))
        self.connection.execute(
            """INSERT INTO sequence_heads VALUES(?,?) ON CONFLICT(sequence_id)
            DO UPDATE SET version=excluded.version""", (sequence_id, next_version))
        return next_version

    def load_sequence(self, sequence_id, version):
        row = self.connection.execute(
            "SELECT body FROM sequence_versions WHERE sequence_id=? AND version=?",
            (sequence_id, version)).fetchone()
        if row is None:
            raise LookupError("unknown sequence version")
        return tuple(ObservationRecord(*r) for r in json.loads(row[0]))

    def save_snapshot(self, snapshot_id, body):
        self.connection.execute(
            "INSERT OR IGNORE INTO observation_snapshots VALUES(?,?)", (snapshot_id, body))
        stored = self.load_snapshot(snapshot_id)
        if stored != body:
            raise ValueError("snapshot digest collision")

    def load_snapshot(self, snapshot_id):
        row = self.connection.execute(
            "SELECT body FROM observation_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise LookupError("unknown snapshot")
        return row[0]
