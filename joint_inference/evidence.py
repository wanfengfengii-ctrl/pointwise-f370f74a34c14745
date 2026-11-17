from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from fractions import Fraction
import math
from duration_inference.evidence import (EvidenceValue, ZeroEvidenceError,
                                         InferenceNumericalError)

@dataclass(frozen=True)
class JointEdgeView:
    target: int
    probability: Decimal
    renewal_a: bool
    renewal_b: bool

@dataclass(frozen=True)
class JointEvidenceTrace:
    input_id: str
    device_states: tuple
    symbols: tuple
    phases: tuple
    initial: tuple
    edges: tuple
    emissions: tuple
    scales: tuple
    forward: tuple
    evidence: EvidenceValue

def _to_decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)

def compute_joint_evidence(kernel, symbols, input_id):
    symbols = (tuple(symbols[0]), tuple(symbols[1]))
    phases = kernel.phases
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 70, MAX_EMAX, MIN_EMIN
        initial = tuple(_to_decimal(p) for p in kernel.stationary)
        edges = tuple(
            tuple(JointEdgeView(edge.target, _to_decimal(edge.probability),
                                edge.renewal_a, edge.renewal_b)
                  for edge in source_edges)
            for source_edges in kernel.edges)
        emissions = []
        for time in range(len(symbols[0])):
            row = []
            for pa, pb in phases:
                weight = (kernel.emissions[0][pa.state].get(symbols[0][time], Fraction(0))
                          * kernel.emissions[1][pb.state].get(symbols[1][time], Fraction(0)))
                row.append(_to_decimal(weight))
            emissions.append(tuple(row))
        alpha = initial
        scales, forward = [], []
        mantissa, exponent = Decimal(1), 0
        for time in range(len(symbols[0])):
            if time == 0:
                raw = [p * w for p, w in zip(alpha, emissions[0])]
            else:
                raw = [Decimal(0)] * len(phases)
                current = emissions[time]
                for i, source_edges in enumerate(edges):
                    mass = alpha[i]
                    if not mass:
                        continue
                    for edge in source_edges:
                        raw[edge.target] += mass * edge.probability * current[edge.target]
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
        return JointEvidenceTrace(input_id, kernel.device_states, symbols, phases, initial,
                                  edges, tuple(emissions), tuple(scales), tuple(forward),
                                  value)
