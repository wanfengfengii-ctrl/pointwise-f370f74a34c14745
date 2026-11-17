from runtime_models.schema import (ModelRef, GroupRef, ModelRevision, ModelDefinitionError,
    canonicalize_model, model_digest)
from runtime_models.probabilities import validate_model_probabilities
from runtime_models.stationary import segment_stationary_distribution
from runtime_models.storage import ModelStore, GroupStore
from runtime_models.groups import (GroupRevision, canonicalize_group, group_digest,
    require_group_model_scale)
from joint_inference.kernel import build_joint_kernel

class ModelRegistrationError(ValueError):
    pass

class ModelRevisionConflict(ModelRegistrationError):
    pass

class UnknownModelReference(LookupError):
    pass

class UnknownGroupReference(LookupError):
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

def register_group(connection, revision_id, device_models, shock_probs):
    if not isinstance(revision_id, str) or not revision_id:
        raise ModelDefinitionError("group revision ID must be a nonempty string")
    definition = canonicalize_group(device_models, shock_probs)
    revisions = tuple(resolve_model(connection, ref) for _, ref in definition.devices)
    for revision in revisions:
        require_group_model_scale(revision.definition)
    build_joint_kernel(tuple(revision.definition for revision in revisions),
                       definition.shock_probs)
    ref = GroupRef(revision_id, group_digest(definition))
    group = GroupRevision(ref, definition)
    stored = GroupStore(connection).insert_revision(group)
    if stored != group:
        raise ModelRevisionConflict(revision_id)
    return ref

def resolve_group(connection, ref):
    if not isinstance(ref, GroupRef):
        raise UnknownGroupReference("expected fixed GroupRef")
    revision = GroupStore(connection).find(ref.revision_id)
    if revision is None or revision.ref != ref:
        raise UnknownGroupReference(ref.revision_id)
    if group_digest(revision.definition) != ref.digest:
        raise ModelRegistrationError("stored group digest mismatch")
    return revision
