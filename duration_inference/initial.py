from dataclasses import dataclass
from fractions import Fraction
from runtime_models.stationary import segment_stationary_distribution, mean_durations

@dataclass(frozen=True, order=True)
class ResidualPhase:
    state: int
    remaining: int

def duration_survival(model, state, remaining):
    return sum(Fraction(str(p)) for d, p in model.durations[state] if d >= remaining)

def equilibrium_initial_mass(model):
    pi = segment_stationary_distribution(model)
    lengths = mean_durations(model)
    mean = sum(p * duration for p, duration in zip(pi, lengths))
    return {ResidualPhase(s, r): pi[s] * duration_survival(model, s, r) / mean
            for s in range(len(model.states))
            for r in range(1, max(d for d, _ in model.durations[s]) + 1)}
