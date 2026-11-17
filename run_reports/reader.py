import hashlib
from archive import atomic
import json
from analysis_tasks.storage import TaskStore
from analysis_tasks.bindings import binding_fingerprint
from run_reports.publication import canonical_report
from run_reports.windows import build_window_layout
from run_reports.validation import validate_joint_statistics, validate_occupancy_conservation

class ReportNotPublished(LookupError):
    pass

class ArchiveIntegrityError(RuntimeError):
    pass

def read_report(connection, task_id):
    with atomic(connection):
        return _read_report(connection, task_id)

def _read_report(connection, task_id):
    try:
        task = TaskStore(connection).load_task(task_id)
    except (ValueError, TypeError, KeyError) as error:
        raise ArchiveIntegrityError("invalid task binding") from error
    row = connection.execute(
        "SELECT body FROM run_reports WHERE task_id=?", (task_id,)).fetchone()
    receipt_row = connection.execute(
        "SELECT receipt_id,body FROM publication_receipts WHERE task_id=?",
        (task_id,)).fetchone()
    if row is None and receipt_row is None and (task is None or task[1] is None):
        raise ReportNotPublished(task_id)
    if task is None or row is None or receipt_row is None or task[1] != receipt_row[0]:
        raise ArchiveIntegrityError("incomplete publication")
    try:
        body, receipt = json.loads(row[0]), json.loads(receipt_row[1])
        binding = task[0]
        digest = hashlib.sha256(canonical_report(body).encode()).hexdigest()
        input_id = binding_fingerprint(binding)
        expected_id = hashlib.sha256((input_id + ":" + digest).encode()).hexdigest()
        layout = build_window_layout(binding.states, binding.windows)
        expected = {"task_id": task_id, "input_id": input_id,
                    "report_sha256": digest, "receipt_id": expected_id}
        if receipt != expected or receipt_row[0] != expected_id:
            raise ArchiveIntegrityError("receipt mismatch")
        identities = {"task_id": task_id, "input_id": input_id,
                      "states": list(binding.states),
                      "model_ref": [binding.model_ref.revision_id, binding.model_ref.digest],
                      "sequence_ref": [binding.snapshot.sequence_id, binding.snapshot.version],
                      "snapshot_id": binding.snapshot.snapshot_id,
                      "prefix": binding.snapshot.prefix,
                      "windows": [[w.left, w.right] for w in binding.windows],
                      "dimensions": [list(d) for d in layout.dimensions]}
        if any(body.get(key) != value for key, value in identities.items()):
            raise ArchiveIntegrityError("report binding mismatch")
        if len(body["mean"]) != len(layout.dimensions):
            raise ArchiveIntegrityError("report dimension mismatch")
        validate_joint_statistics(body["mean"], body["covariance"])
        validate_occupancy_conservation(binding, body["mean"], body["covariance"])
    except (ValueError, TypeError, KeyError, ArithmeticError) as error:
        raise ArchiveIntegrityError("invalid archived report") from error
    body["receipt"] = receipt
    return body
