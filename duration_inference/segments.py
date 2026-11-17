from dataclasses import dataclass
from decimal import Decimal
from duration_inference.initial import ResidualPhase

@dataclass(frozen=True)
class SegmentEdge:
    source: ResidualPhase
    target: ResidualPhase
    probability: Decimal
    renewal: bool

def phase_space(model):
    return tuple(ResidualPhase(s, r) for s in range(len(model.states))
                 for r in range(1, max(d for d, _ in model.durations[s]) + 1))

def outgoing_edges(model, phase):
    if phase.remaining > 1:
        yield SegmentEdge(phase, ResidualPhase(phase.state, phase.remaining - 1),
                          Decimal(1), False)
    else:
        for target, probability in enumerate(model.transition[phase.state]):
            for duration, mass in model.durations[target]:
                if probability > 0 and mass > 0:
                    yield SegmentEdge(phase, ResidualPhase(target, duration),
                                      Decimal(str(probability)) * Decimal(str(mass)), True)

def emission_weight(model, phase, symbol):
    return Decimal(str(dict(model.emissions[phase.state]).get(symbol, 0)))
