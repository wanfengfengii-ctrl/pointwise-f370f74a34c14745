import json
from archive import atomic
from analysis_tasks.bindings import TaskBinding, binding_fingerprint

class TaskStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self):
        self.connection.execute("""CREATE TABLE IF NOT EXISTS analysis_tasks(
            task_id TEXT PRIMARY KEY, input_id TEXT NOT NULL, binding TEXT NOT NULL,
            receipt_id TEXT)""")

    def transaction(self):
        return atomic(self.connection)

    def insert_binding(self, binding):
        self.connection.execute(
            "INSERT OR IGNORE INTO analysis_tasks VALUES(?,?,?,NULL)",
            (binding.task_id, binding_fingerprint(binding),
             json.dumps(binding.to_data(), sort_keys=True, separators=(",", ":"))))

    def load_task(self, task_id):
        row = self.connection.execute(
            "SELECT input_id,binding,receipt_id FROM analysis_tasks WHERE task_id=?",
            (task_id,)).fetchone()
        if row is None:
            return None
        binding = TaskBinding.from_data(json.loads(row[1]))
        if binding.task_id != task_id or binding_fingerprint(binding) != row[0]:
            raise ValueError("task binding integrity failure")
        return binding, row[2]

    def set_published(self, task_id, receipt_id):
        cursor = self.connection.execute(
            "UPDATE analysis_tasks SET receipt_id=? WHERE task_id=? AND receipt_id IS NULL",
            (receipt_id, task_id))
        if cursor.rowcount != 1:
            raise ValueError("task is missing or already published")
