from dataclasses import dataclass
import hashlib
import json
from runtime_models.schema import ModelRef
from observations.snapshots import ObservationSnapshot
from analysis_tasks.requests import WindowRequest

@dataclass(frozen=True)
class TaskBinding:
    task_id: str
    model_ref: ModelRef
    snapshot: ObservationSnapshot
    states: tuple
    windows: tuple

    def to_data(self):
        return {"task_id": self.task_id,
                "model_ref": [self.model_ref.revision_id, self.model_ref.digest],
                "snapshot": self.snapshot.to_data(), "states": self.states,
                "windows": [[w.left, w.right] for w in self.windows]}

    @classmethod
    def from_data(cls, data):
        return cls(data["task_id"], ModelRef(*data["model_ref"]),
                   ObservationSnapshot.from_data(data["snapshot"]),
                   tuple(data["states"]), tuple(WindowRequest(*w) for w in data["windows"]))

def build_binding(request, revision, snapshot):
    return TaskBinding(request.task_id, revision.ref, snapshot,
                       revision.definition.states, tuple(request.windows))

def binding_fingerprint(binding):
    body = json.dumps(binding.to_data(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()

def same_binding(left, right):
    return left == right
