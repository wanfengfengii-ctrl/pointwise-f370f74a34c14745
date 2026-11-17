from dataclasses import dataclass
from fractions import Fraction
from duration_inference.initial import ResidualPhase
from duration_inference.segments import phase_space
from runtime_models.stationary import StationaryDistributionError

@dataclass(frozen=True)
class JointEdge:
    target: int
    probability: Fraction
    renewal_a: bool
    renewal_b: bool

@dataclass(frozen=True)
class JointKernel:
    device_states: tuple
    phases: tuple
    edges: tuple
    stationary: tuple
    emissions: tuple

def _normalized(values):
    values = [Fraction(str(value)) for value in values]
    total = sum(values, Fraction(0))
    return tuple(value / total for value in values)

def _device_tables(model):
    transition = tuple(_normalized(row) for row in model.transition)
    durations = tuple(
        tuple((key, probability)
              for (key, _), probability in zip(row, _normalized([p for _, p in row])))
        for row in model.durations)
    emissions = tuple(
        dict(zip([key for key, _ in row], _normalized([p for _, p in row])))
        for row in model.emissions)
    return transition, durations, emissions

def _branches(transition, durations, phase, shocked):
    if phase.remaining == 1 or shocked:
        branches = []
        for target, probability in enumerate(transition[phase.state]):
            if probability <= 0:
                continue
            for duration, mass in durations[target]:
                if mass > 0:
                    branches.append((ResidualPhase(target, duration),
                                     probability * mass, True))
        return tuple(branches)
    return ((ResidualPhase(phase.state, phase.remaining - 1), Fraction(1), False),)

def build_joint_kernel(models, shock_probs):
    model_a, model_b = models
    tables = (_device_tables(model_a), _device_tables(model_b))
    shock = _normalized(shock_probs)
    phases_a = phase_space(model_a)
    phases_b = phase_space(model_b)
    phases = tuple((pa, pb) for pa in phases_a for pb in phases_b)
    index = {phase: position for position, phase in enumerate(phases)}
    edges = []
    for pa, pb in phases:
        acc = {}
        for subset in range(4):
            weight = shock[subset]
            if not weight:
                continue
            branches_a = _branches(tables[0][0], tables[0][1], pa, subset in (1, 3))
            branches_b = _branches(tables[1][0], tables[1][1], pb, subset in (2, 3))
            for target_a, prob_a, renewal_a in branches_a:
                for target_b, prob_b, renewal_b in branches_b:
                    key = (index[(target_a, target_b)], renewal_a, renewal_b)
                    acc[key] = acc.get(key, Fraction(0)) + weight * prob_a * prob_b
        edges.append(tuple(JointEdge(target, probability, renewal_a, renewal_b)
                           for (target, renewal_a, renewal_b), probability
                           in sorted(acc.items())))
    stationary = _unique_stationary(len(phases), edges)
    return JointKernel((model_a.states, model_b.states), phases, tuple(edges),
                       stationary, (tables[0][2], tables[1][2]))

def _unique_stationary(count, edges):
    kernel = [[Fraction(0)] * count for _ in range(count)]
    for source, source_edges in enumerate(edges):
        for edge in source_edges:
            kernel[source][edge.target] += edge.probability
    rows = []
    for col in range(count):
        rows.append([kernel[line][col] - (Fraction(1) if line == col else Fraction(0))
                     for line in range(count)] + [Fraction(0)])
    rows.append([Fraction(1)] * count + [Fraction(1)])
    for col in range(count):
        pivot = next((r for r in range(col, count + 1) if rows[r][col]), None)
        if pivot is None:
            raise StationaryDistributionError("joint stationary distribution is not unique")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [value / divisor for value in rows[col]]
        for r in range(count + 1):
            if r != col and rows[r][col]:
                multiplier = rows[r][col]
                rows[r] = [x - multiplier * y for x, y in zip(rows[r], rows[col])]
    stationary = tuple(rows[r][-1] for r in range(count))
    if any(p < 0 for p in stationary):
        raise StationaryDistributionError("joint stationary mass must be nonnegative")
    return stationary
