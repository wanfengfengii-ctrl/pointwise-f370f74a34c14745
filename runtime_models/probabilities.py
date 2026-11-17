import math
from runtime_models.schema import ModelDefinitionError

class ProbabilityValidationError(ModelDefinitionError):
    pass

def validate_distribution(values):
    values = tuple(values)
    if not values or any(not math.isfinite(p) or p < 0 for p in values):
        raise ProbabilityValidationError("probabilities must be finite and nonnegative")
    if abs(math.fsum(values) - 1.0) > 1e-12:
        raise ProbabilityValidationError("probability row must sum to one")

def require_irreducible(transition):
    n = len(transition)
    for start in range(n):
        seen, pending = {start}, [start]
        while pending:
            source = pending.pop()
            for target, p in enumerate(transition[source]):
                if p > 0 and target not in seen:
                    seen.add(target)
                    pending.append(target)
        if len(seen) != n:
            raise ProbabilityValidationError("segment transition must be irreducible")

def validate_model_probabilities(model):
    for row in model.transition:
        validate_distribution(row)
    for table in (model.durations, model.emissions):
        for row in table:
            validate_distribution(p for _, p in row)
    require_irreducible(model.transition)
