from dataclasses import dataclass, asdict
import hashlib
import json
from analysis_tasks.bindings import binding_fingerprint
from analysis_tasks.catalog import TaskCatalog
from analysis_tasks.storage import TaskStore
from run_reports.validation import validate_joint_statistics, validate_occupancy_conservation

class PublicationError(RuntimeError):
    pass

@dataclass(frozen=True)
class PublicationReceipt:
    receipt_id: str
    task_id: str
    input_id: str
    report_sha256: str

def canonical_report(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)

def initialize_report_archive(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS run_reports(
        task_id TEXT PRIMARY KEY REFERENCES analysis_tasks(task_id),
        body TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS publication_receipts(
        task_id TEXT PRIMARY KEY REFERENCES run_reports(task_id),
        receipt_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL)""")

def publish_report(connection, binding, report, *, before_commit=None):
    body = report.to_data()
    if body["task_id"] != binding.task_id or body["input_id"] != binding_fingerprint(binding):
        raise PublicationError("publication input mismatch")
    validate_joint_statistics(body["mean"], body["covariance"])
    validate_occupancy_conservation(binding, body["mean"], body["covariance"])
    encoded = canonical_report(body)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    receipt_id = hashlib.sha256((body["input_id"] + ":" + digest).encode()).hexdigest()
    receipt = PublicationReceipt(receipt_id, binding.task_id, body["input_id"], digest)
    try:
        with TaskStore(connection).transaction():
            current, published = TaskCatalog(connection).require_frozen(binding.task_id)
            if current != binding:
                raise PublicationError("task changed")
            if published is not None:
                from run_reports.reader import read_report
                return read_report(connection, binding.task_id)
            connection.execute("INSERT INTO run_reports VALUES(?,?)",
                               (binding.task_id, encoded))
            connection.execute("INSERT INTO publication_receipts VALUES(?,?,?)",
                               (binding.task_id, receipt_id, canonical_report(asdict(receipt))))
            TaskCatalog(connection).mark_published(binding.task_id, receipt_id)
            if before_commit is not None:
                before_commit()
    except Exception as error:
        raise PublicationError("report publication rolled back") from error
    from run_reports.reader import read_report
    return read_report(connection, binding.task_id)
