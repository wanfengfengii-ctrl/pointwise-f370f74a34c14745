from runtime_models.schema import (ModelRef, ModelRevision, ModelDefinitionError,
    canonicalize_model, model_digest)
from runtime_models.probabilities import validate_model_probabilities
from runtime_models.stationary import segment_stationary_distribution
from runtime_models.storage import ModelStore

class ModelRegistrationError(ValueError):
    pass

class ModelRevisionConflict(ModelRegistrationError):
    pass

class UnknownModelReference(LookupError):
    pass

def register_model(connection, revision_id, definition):
    if not isinstance(revision_id, str) or not revision_id:
        raise ModelDefinitionError("revision ID must be a nonempty string")
    model = canonicalize_model(definition)
    validate_model_probabilities(model)
    segment_stationary_distribution(model)
    ref = ModelRef(revision_id, model_digest(model))
    stored = ModelStore(connection).insert_revision(ModelRevision(ref, model))
    if stored.ref != ref or stored.definition != model:
        raise ModelRevisionConflict(revision_id)
    return ref

def resolve_model(connection, ref):
    if not isinstance(ref, ModelRef):
        raise UnknownModelReference("expected fixed ModelRef")
    revision = ModelStore(connection).find(ref.revision_id)
    if revision is None or revision.ref != ref:
        raise UnknownModelReference(ref.revision_id)
    if model_digest(revision.definition) != ref.digest:
        raise ModelRegistrationError("stored model digest mismatch")
    return revision
