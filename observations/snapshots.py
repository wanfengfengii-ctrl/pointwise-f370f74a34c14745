from dataclasses import dataclass
import hashlib
import json
from observations.records import ObservationRecord
from observations.sequences import read_sequence_revision
from observations.storage import ObservationStore

class SnapshotReferenceError(LookupError):
    pass

@dataclass(frozen=True)
class ObservationSnapshot:
    snapshot_id: str
    sequence_id: str
    version: int
    prefix: int
    records: tuple

    def to_data(self):
        return {"sequence_id": self.sequence_id, "version": self.version,
                "prefix": self.prefix, "records": [r.to_data() for r in self.records]}

    @classmethod
    def from_data(cls, data):
        body = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return cls(hashlib.sha256(body.encode()).hexdigest(), data["sequence_id"],
                   data["version"], data["prefix"],
                   tuple(ObservationRecord(*r) for r in data["records"]))

def seal_prefix(connection, revision, prefix):
    try:
        records = read_sequence_revision(connection, revision)
    except LookupError as error:
        raise SnapshotReferenceError(str(error)) from error
    if type(prefix) is not int or not 0 <= prefix <= len(records):
        raise SnapshotReferenceError("prefix out of bounds")
    data = {"sequence_id": revision.sequence_id, "version": revision.version,
            "prefix": prefix, "records": [r.to_data() for r in records[:prefix]]}
    snapshot = ObservationSnapshot.from_data(data)
    body = json.dumps(data, sort_keys=True, separators=(",", ":"))
    ObservationStore(connection).save_snapshot(snapshot.snapshot_id, body)
    return snapshot

def load_snapshot(connection, snapshot_id):
    try:
        data = json.loads(ObservationStore(connection).load_snapshot(snapshot_id))
        snapshot = ObservationSnapshot.from_data(data)
    except (LookupError, ValueError, KeyError, TypeError) as error:
        raise SnapshotReferenceError("invalid snapshot") from error
    if snapshot.snapshot_id != snapshot_id or len(snapshot.records) != snapshot.prefix:
        raise SnapshotReferenceError("snapshot identity mismatch")
    return snapshot
