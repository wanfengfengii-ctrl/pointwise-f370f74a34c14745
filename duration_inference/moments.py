from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import math
from duration_inference.segments import outgoing_edges, emission_weight

@dataclass(frozen=True)
class RewardPlan:
    input_id: str
    states: tuple
    dimensions: tuple
    node_rewards: tuple
    renewal_rewards: tuple

    def reward(self, time, state, renewal):
        node = self.node_rewards[time][state]
        edge = self.renewal_rewards[time]
        return tuple(x + (y if renewal else 0) for x, y in zip(node, edge))

@dataclass(frozen=True)
class ConditionalMoments:
    input_id: str
    states: tuple
    dimensions: tuple
    evidence: object
    mean: tuple
    second: tuple

def validate_reward_plan(trace, plan):
    n, k, m = len(trace.symbols), len(trace.model.states), len(plan.dimensions)
    if trace.input_id != plan.input_id or plan.states != trace.model.states:
        raise ValueError("reward input identity mismatch")
    if len(plan.node_rewards) != n or len(plan.renewal_rewards) != n:
        raise ValueError("reward time shape")
    for nodes, edge in zip(plan.node_rewards, plan.renewal_rewards):
        if len(nodes) != k or len(edge) != m or any(len(row) != m for row in nodes):
            raise ValueError("reward vector shape")
        if any(not math.isfinite(x) for row in (*nodes, edge) for x in row):
            raise ValueError("nonfinite reward")

def compute_conditional_moments(trace, plan):
    validate_reward_plan(trace, plan)
    m, count = len(plan.dimensions), len(trace.phases)
    if not trace.symbols:
        return ConditionalMoments(trace.input_id, plan.states, plan.dimensions,
                                  trace.evidence, (Decimal(0),) * m,
                                  tuple((Decimal(0),) * m for _ in range(m)))
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 70, MAX_EMAX, MIN_EMIN
        weights = list(trace.forward[0])
        first, second = [], []
        for phase, weight in zip(trace.phases, weights):
            reward = tuple(Decimal(str(x)) for x in plan.reward(0, phase.state, False))
            first.append([weight * x for x in reward])
            second.append([[weight * x * y for y in reward] for x in reward])
        index = {phase: i for i, phase in enumerate(trace.phases)}
        for time in range(1, len(trace.symbols)):
            next_weights = [Decimal(0)] * count
            next_first = [[Decimal(0)] * m for _ in range(count)]
            next_second = [[[Decimal(0)] * m for _ in range(m)] for _ in range(count)]
            for source, phase in enumerate(trace.phases):
                for edge in outgoing_edges(trace.model, phase):
                    target = index[edge.target]
                    factor = (edge.probability * emission_weight(
                        trace.model, edge.target, trace.symbols[time]) / trace.scales[time])
                    reward = tuple(Decimal(str(x)) for x in plan.reward(
                        time, edge.target.state, edge.renewal))
                    p, u, v = weights[source], first[source], second[source]
                    next_weights[target] += p * factor
                    for i in range(m):
                        next_first[target][i] += (u[i] + p * reward[i]) * factor
                        for j in range(m):
                            next_second[target][i][j] += (
                                v[i][j] + u[i] * reward[j] + u[j] * reward[i]
                                + p * reward[i] * reward[j]) * factor
            weights, first, second = next_weights, next_first, next_second
        denominator = sum(weights, Decimal(0))
        if abs(denominator - 1) > Decimal("1e-50"):
            raise ArithmeticError("moment and evidence normalization disagree")
        means = tuple(sum(row[i] for row in first) / denominator for i in range(m))
        raw = tuple(tuple(sum(mat[i][j] for mat in second) / denominator
                          for j in range(m)) for i in range(m))
        return ConditionalMoments(trace.input_id, plan.states, plan.dimensions,
                                  trace.evidence, means, raw)
