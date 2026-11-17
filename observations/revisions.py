from dataclasses import dataclass
from observations.records import validate_record, same_record_content

class RevisionConflict(ValueError):
    pass

@dataclass(frozen=True)
class RevisionPlan:
    received: tuple
    current: tuple
    changed: bool

def compare_source_revisions(left, right):
    return (left > right) - (left < right)

def plan_revision_batch(current, history, records):
    received = {}
    for raw in records:
        record = validate_record(raw)
        key = (record.identity, record.source_revision)
        previous = received.get(key, history.get(key))
        if previous is not None and not same_record_content(previous, record):
            raise RevisionConflict(str(key))
        received[key] = record
    final = dict(current)
    for record in received.values():
        previous = final.get(record.identity)
        if previous is None or compare_source_revisions(
                record.source_revision, previous.source_revision) > 0:
            final[record.identity] = record
    return RevisionPlan(tuple(received.values()), tuple(final.values()), final != current)
