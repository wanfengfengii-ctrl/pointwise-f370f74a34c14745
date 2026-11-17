import json
from archive import atomic
from runtime_models.schema import ModelRef, GroupRef, ModelRevision, model_json, model_from_data
from runtime_models.groups import GroupRevision, group_json, group_from_data

class ModelStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self):
        self.connection.execute("""CREATE TABLE IF NOT EXISTS model_revisions(
            revision_id TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL)""")

    def find(self, revision_id):
        row = self.connection.execute(
            "SELECT digest,body FROM model_revisions WHERE revision_id=?",
            (revision_id,)).fetchone()
        if row is None:
            return None
        return ModelRevision(ModelRef(revision_id, row[0]),
                             model_from_data(json.loads(row[1])))

    def insert_revision(self, revision):
        with atomic(self.connection):
            self.connection.execute(
                "INSERT OR IGNORE INTO model_revisions VALUES(?,?,?)",
                (revision.ref.revision_id, revision.ref.digest,
                 model_json(revision.definition)))
            return self.find(revision.ref.revision_id)

class GroupStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self):
        self.connection.execute("""CREATE TABLE IF NOT EXISTS group_revisions(
            revision_id TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL)""")

    def find(self, revision_id):
        row = self.connection.execute(
            "SELECT digest,body FROM group_revisions WHERE revision_id=?",
            (revision_id,)).fetchone()
        if row is None:
            return None
        return GroupRevision(GroupRef(revision_id, row[0]),
                             group_from_data(json.loads(row[1])))

    def insert_revision(self, revision):
        with atomic(self.connection):
            self.connection.execute(
                "INSERT OR IGNORE INTO group_revisions VALUES(?,?,?)",
                (revision.ref.revision_id, revision.ref.digest,
                 group_json(revision.definition)))
            return self.find(revision.ref.revision_id)
