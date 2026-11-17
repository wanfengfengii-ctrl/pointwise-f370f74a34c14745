from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import math
from duration_inference.initial import equilibrium_initial_mass
from duration_inference.segments import phase_space, outgoing_edges, emission_weight

class ZeroEvidenceError(ArithmeticError):
    pass

class InferenceNumericalError(ArithmeticError):
    pass

@dataclass(frozen=True)
class EvidenceValue:
    mantissa: str
    exponent: int
    log_evidence: float
    probability: float | None

    def to_data(self):
        return {"mantissa": self.mantissa, "exponent": self.exponent,
                "log_evidence": self.log_evidence, "probability": self.probability,
                "probability_representable": self.probability is not None}

@dataclass(frozen=True)
class EvidenceTrace:
    input_id: str
    model: object
    symbols: tuple
    phases: tuple
    initial: tuple
    scales: tuple
    forward: tuple
    evidence: EvidenceValue

def compute_evidence(model, symbols, input_id):
    symbols = tuple(symbols)
    phases = phase_space(model)
    index = {phase: i for i, phase in enumerate(phases)}
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 70, MAX_EMAX, MIN_EMIN
        mass = equilibrium_initial_mass(model)
        initial = tuple(Decimal(mass[p].numerator) / Decimal(mass[p].denominator)
                        for p in phases)
        alpha = initial
        scales, forward = [], []
        mantissa, exponent = Decimal(1), 0
        for time, symbol in enumerate(symbols):
            if time == 0:
                raw = [p * emission_weight(model, phase, symbol)
                       for p, phase in zip(alpha, phases)]
            else:
                raw = [Decimal(0)] * len(phases)
                for i, phase in enumerate(phases):
                    for edge in outgoing_edges(model, phase):
                        raw[index[edge.target]] += (
                            alpha[i] * edge.probability
                            * emission_weight(model, edge.target, symbol))
            scale = sum(raw, Decimal(0))
            if not scale:
                raise ZeroEvidenceError("observations have zero evidence")
            if not scale.is_finite() or scale < 0:
                raise InferenceNumericalError("invalid evidence scale")
            alpha = tuple(p / scale for p in raw)
            scales.append(scale)
            forward.append(alpha)
            combined = mantissa * scale
            shift = combined.adjusted()
            mantissa = combined.scaleb(-shift)
            exponent += shift
        log_evidence = float(mantissa.ln()) + exponent * math.log(10)
        if not math.isfinite(log_evidence):
            raise InferenceNumericalError("nonfinite log evidence")
        probability = float(mantissa.scaleb(exponent))
        if probability == 0 or not math.isfinite(probability):
            probability = None
        value = EvidenceValue(str(mantissa), exponent, log_evidence, probability)
        return EvidenceTrace(input_id, model, symbols, phases, initial,
                             tuple(scales), tuple(forward), value)
