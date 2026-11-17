from analysis_tasks.bindings import same_binding
from analysis_tasks.storage import TaskStore

class TaskIdConflict(ValueError):
    pass

class UnknownTask(LookupError):
    pass

class TaskCatalog:
    def __init__(self, connection):
        self.store = TaskStore(connection)

    def freeze_binding(self, binding):
        with self.store.transaction():
            self.store.insert_binding(binding)
            existing = self.get_binding(binding.task_id)
            if not same_binding(existing, binding):
                raise TaskIdConflict(binding.task_id)
            return existing

    def get_binding(self, task_id):
        row = self.store.load_task(task_id)
        if row is None:
            raise UnknownTask(task_id)
        return row[0]

    def require_frozen(self, task_id):
        row = self.store.load_task(task_id)
        if row is None:
            raise UnknownTask(task_id)
        return row

    def mark_published(self, task_id, receipt_id):
        if not self.store.connection.in_transaction:
            raise RuntimeError("publication requires an archive transaction")
        row = self.store.connection.execute(
            """SELECT p.receipt_id FROM publication_receipts p
            JOIN run_reports r ON r.task_id=p.task_id
            WHERE p.task_id=? AND p.receipt_id=?""", (task_id, receipt_id)).fetchone()
        if row is None:
            raise ValueError("complete report and receipt required")
        self.store.set_published(task_id, receipt_id)
