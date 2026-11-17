from dataclasses import dataclass
import hashlib
import json
from runtime_models.schema import ModelRef, GroupRef
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

@dataclass(frozen=True)
class GroupDeviceBinding:
    device_id: str
    model_ref: ModelRef
    states: tuple
    snapshot: ObservationSnapshot

    def to_data(self):
        return {"device_id": self.device_id,
                "model_ref": [self.model_ref.revision_id, self.model_ref.digest],
                "states": self.states, "snapshot": self.snapshot.to_data()}

    @classmethod
    def from_data(cls, data):
        return cls(data["device_id"], ModelRef(*data["model_ref"]),
                   tuple(data["states"]), ObservationSnapshot.from_data(data["snapshot"]))

    def report_data(self):
        return {"device_id": self.device_id,
                "model_ref": [self.model_ref.revision_id, self.model_ref.digest],
                "states": list(self.states),
                "sequence_ref": [self.snapshot.sequence_id, self.snapshot.version],
                "snapshot_id": self.snapshot.snapshot_id,
                "records": [record.to_data() for record in self.snapshot.records]}

@dataclass(frozen=True)
class GroupTaskBinding:
    task_id: str
    group_ref: GroupRef
    devices: tuple
    windows: tuple
    prefix: int

    def to_data(self):
        return {"task_id": self.task_id,
                "group_ref": [self.group_ref.revision_id, self.group_ref.digest],
                "devices": [device.to_data() for device in self.devices],
                "windows": [[w.left, w.right] for w in self.windows],
                "prefix": self.prefix}

    @classmethod
    def from_data(cls, data):
        return cls(data["task_id"], GroupRef(*data["group_ref"]),
                   tuple(GroupDeviceBinding.from_data(device) for device in data["devices"]),
                   tuple(WindowRequest(*w) for w in data["windows"]), data["prefix"])

def build_group_binding(request, group_revision, model_revisions, snapshots):
    devices = tuple(
        GroupDeviceBinding(device_id, model_ref, tuple(revision.definition.states), snapshot)
        for (device_id, model_ref), revision, snapshot
        in zip(group_revision.definition.devices, model_revisions, snapshots))
    return GroupTaskBinding(request.task_id, group_revision.ref, devices,
                            tuple(request.windows), request.prefix)

def binding_from_data(data):
    if "group_ref" in data:
        return GroupTaskBinding.from_data(data)
    return TaskBinding.from_data(data)

def binding_fingerprint(binding):
    body = json.dumps(binding.to_data(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()

def same_binding(left, right):
    return left == right
