from dataclasses import dataclass
import hashlib
import json
from runtime_models.schema import ModelRef, GroupRef, ModelDefinitionError
from runtime_models.probabilities import validate_distribution

@dataclass(frozen=True)
class GroupDefinition:
    devices: tuple
    shock_probs: tuple

    def to_data(self):
        return {"devices": [[device_id, [ref.revision_id, ref.digest]]
                            for device_id, ref in self.devices],
                "shock_probs": list(self.shock_probs)}

@dataclass(frozen=True)
class GroupRevision:
    ref: GroupRef
    definition: GroupDefinition

def canonicalize_group(device_models, shock_probs):
    try:
        if not isinstance(device_models, (list, tuple)) or len(device_models) != 2:
            raise ModelDefinitionError("exactly two device models required")
        devices = []
        for entry in device_models:
            device_id, ref = entry
            if not isinstance(device_id, str) or not device_id:
                raise ModelDefinitionError("device ID must be a nonempty string")
            devices.append((device_id, ref))
        if devices[0][0] == devices[1][0]:
            raise ModelDefinitionError("device IDs must differ")
        probs = tuple(shock_probs)
        if len(probs) != 4:
            raise ModelDefinitionError("exactly four shock probabilities required")
        canonical = []
        for value in probs:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ModelDefinitionError("shock probabilities must be int or float")
            canonical.append(float(value))
        validate_distribution(canonical)
        return GroupDefinition(tuple(devices), tuple(canonical))
    except ModelDefinitionError:
        raise
    except (TypeError, ValueError, AttributeError) as error:
        raise ModelDefinitionError("malformed group") from error

def require_group_model_scale(definition):
    if not 1 <= len(definition.states) <= 2:
        raise ModelDefinitionError("group device models allow one or two states")
    for row in definition.durations:
        if any(not 1 <= key <= 2 for key, _ in row):
            raise ModelDefinitionError("group device models allow duration keys one and two")

def group_json(definition):
    return json.dumps(definition.to_data(), sort_keys=True, separators=(",", ":"),
                      allow_nan=False)

def group_digest(definition):
    return hashlib.sha256(group_json(definition).encode()).hexdigest()

def group_from_data(data):
    return GroupDefinition(
        tuple((device_id, ModelRef(ref, digest))
              for device_id, (ref, digest) in data["devices"]),
        tuple(data["shock_probs"]))
