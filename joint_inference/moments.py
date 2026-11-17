from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import math

@dataclass(frozen=True)
class GroupRewardPlan:
    input_id: str
    device_states: tuple
    dimensions: tuple
    node_rewards: tuple
    renewal_rewards: tuple

    def reward(self, time, joint_index, renewal_a, renewal_b):
        node = self.node_rewards[time][joint_index]
        if renewal_a:
            node = tuple(x + y for x, y in zip(node, self.renewal_rewards[0][time]))
        if renewal_b:
            node = tuple(x + y for x, y in zip(node, self.renewal_rewards[1][time]))
        return node

@dataclass(frozen=True)
class JointConditionalMoments:
    input_id: str
    device_states: tuple
    dimensions: tuple
    evidence: object
    mean: tuple
    second: tuple

def validate_group_reward_plan(trace, plan):
    n, m = len(trace.symbols[0]), len(plan.dimensions)
    if trace.input_id != plan.input_id or plan.device_states != trace.device_states:
        raise ValueError("reward input identity mismatch")
    if (len(plan.node_rewards) != n or len(plan.renewal_rewards[0]) != n
            or len(plan.renewal_rewards[1]) != n):
        raise ValueError("reward time shape")
    for nodes, vec_a, vec_b in zip(plan.node_rewards, *plan.renewal_rewards):
        if (len(nodes) != len(trace.phases) or len(vec_a) != m or len(vec_b) != m
                or any(len(row) != m for row in nodes)):
            raise ValueError("reward vector shape")
        if any(not math.isfinite(x) for row in (*nodes, vec_a, vec_b) for x in row):
            raise ValueError("nonfinite reward")

def compute_joint_conditional_moments(trace, plan):
    validate_group_reward_plan(trace, plan)
    m, count = len(plan.dimensions), len(trace.phases)
    if not trace.symbols[0]:
        return JointConditionalMoments(trace.input_id, plan.device_states, plan.dimensions,
                                       trace.evidence, (Decimal(0),) * m,
                                       tuple((Decimal(0),) * m for _ in range(m)))
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 70, MAX_EMAX, MIN_EMIN
        weights = list(trace.forward[0])
        first, second = [], []
        for joint_index, weight in enumerate(weights):
            reward = tuple(Decimal(x) for x in plan.reward(0, joint_index, False, False))
            first.append([weight * x for x in reward])
            second.append([[weight * x * y for y in reward] for x in reward])
        for time in range(1, len(trace.symbols[0])):
            scale = trace.scales[time]
            emissions = trace.emissions[time]
            next_weights = [Decimal(0)] * count
            next_first = [[Decimal(0)] * m for _ in range(count)]
            next_second = [[[Decimal(0)] * m for _ in range(m)] for _ in range(count)]
            for source in range(count):
                p = weights[source]
                if not p:
                    continue
                u, v = first[source], second[source]
                for edge in trace.edges[source]:
                    factor = edge.probability * emissions[edge.target] / scale
                    if not factor:
                        continue
                    reward = tuple(Decimal(x) for x in plan.reward(
                        time, edge.target, edge.renewal_a, edge.renewal_b))
                    target = edge.target
                    next_weights[target] += p * factor
                    nf, ns = next_first[target], next_second[target]
                    for i in range(m):
                        ri = reward[i]
                        ui = u[i]
                        nf[i] += (ui + p * ri) * factor
                        vi = v[i]
                        nsi = ns[i]
                        for j in range(m):
                            nsi[j] += (vi[j] + ui * reward[j] + u[j] * ri
                                       + p * ri * reward[j]) * factor
            weights, first, second = next_weights, next_first, next_second
        denominator = sum(weights, Decimal(0))
        if abs(denominator - 1) > Decimal("1e-50"):
            raise ArithmeticError("moment and evidence normalization disagree")
        means = tuple(sum(row[i] for row in first) / denominator for i in range(m))
        raw = tuple(tuple(sum(mat[i][j] for mat in second) / denominator
                          for j in range(m)) for i in range(m))
        return JointConditionalMoments(trace.input_id, plan.device_states, plan.dimensions,
                                       trace.evidence, means, raw)
