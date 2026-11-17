from dataclasses import dataclass
from archive import atomic
from observations.revisions import plan_revision_batch
from observations.storage import ObservationStore

class SequenceConsistencyError(ValueError):
    pass

@dataclass(frozen=True)
class SequenceRevision:
    sequence_id: str
    version: int

def revise_observations(connection, sequence_id, records):
    if not isinstance(sequence_id, str) or not sequence_id:
        raise SequenceConsistencyError("sequence ID must be a nonempty string")
    records = tuple(records)
    store = ObservationStore(connection)
    with atomic(connection):
        current, history, version = store.load_revision_state(sequence_id)
        plan = plan_revision_batch(current, history, records)
        ordered = tuple(sorted(plan.current, key=lambda r: (r.time, r.identity)))
        if len({r.time for r in ordered}) != len(ordered):
            raise SequenceConsistencyError("distinct observations require distinct times")
        version = store.commit_revision_plan(sequence_id, plan, ordered, version)
    return SequenceRevision(sequence_id, version)

def read_sequence_revision(connection, revision):
    if (not isinstance(revision, SequenceRevision) or type(revision.version) is not int
            or revision.version < 1):
        raise LookupError("expected fixed sequence revision")
    return ObservationStore(connection).load_sequence(revision.sequence_id, revision.version)
