from dataclasses import dataclass
import hashlib
import json

class ModelDefinitionError(ValueError):
    pass

@dataclass(frozen=True)
class ModelRef:
    revision_id: str
    digest: str

@dataclass(frozen=True)
class ModelDefinition:
    states: tuple
    transition: tuple
    durations: tuple
    emissions: tuple

    def to_data(self):
        return {"states": self.states, "transition": self.transition,
                "durations": self.durations, "emissions": self.emissions}

@dataclass(frozen=True)
class ModelRevision:
    ref: ModelRef
    definition: ModelDefinition

def canonicalize_model(definition):
    try:
        if not isinstance(definition, ModelDefinition):
            raise ModelDefinitionError("expected ModelDefinition")
        states = tuple(definition.states)
        if (not states or any(not isinstance(s, str) or not s for s in states)
                or len(set(states)) != len(states)):
            raise ModelDefinitionError("states must be unique nonempty strings")
        n = len(states)
        def probability(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ModelDefinitionError("probabilities must be int or float")
            return float(value)
        transition = tuple(tuple(probability(p) for p in row)
                           for row in definition.transition)
        if len(transition) != n or any(len(row) != n for row in transition):
            raise ModelDefinitionError("transition shape")
        tables = []
        for source, duration in ((definition.durations, True),
                                 (definition.emissions, False)):
            if len(source) != n:
                raise ModelDefinitionError("one table per state required")
            rows = []
            for row in source:
                pairs = tuple((key, probability(value)) for key, value in row)
                keys = [key for key, _ in pairs]
                if duration:
                    legal = all(type(k) is int and k > 0 for k in keys)
                else:
                    legal = all(isinstance(k, str) and k for k in keys)
                if not legal or len(set(keys)) != len(keys):
                    raise ModelDefinitionError("invalid or duplicate table key")
                rows.append(tuple(sorted(pairs)))
            tables.append(tuple(rows))
        return ModelDefinition(states, transition, *tables)
    except ModelDefinitionError:
        raise
    except (TypeError, OverflowError, AttributeError, ValueError) as error:
        raise ModelDefinitionError("malformed model") from error

def model_json(definition):
    return json.dumps(definition.to_data(), sort_keys=True, separators=(",", ":"),
                      allow_nan=False)

def model_digest(definition):
    return hashlib.sha256(model_json(definition).encode()).hexdigest()

def model_from_data(data):
    return canonicalize_model(ModelDefinition(**data))
