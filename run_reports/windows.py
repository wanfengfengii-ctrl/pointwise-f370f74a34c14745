from dataclasses import dataclass
from duration_inference.moments import RewardPlan

@dataclass(frozen=True)
class WindowLayout:
    states: tuple
    windows: tuple
    dimensions: tuple

def build_window_layout(states, windows):
    dimensions = []
    for number, window in enumerate(windows):
        dimensions.extend((number, "occupancy", state) for state in states)
        dimensions.append((number, "renewals", ""))
    return WindowLayout(tuple(states), tuple(windows), tuple(dimensions))

def renewal_belongs_to_window(window, time, length):
    return 1 <= time < length and window.left <= time < window.right

def compile_reward_plan(binding, layout):
    from analysis_tasks.bindings import binding_fingerprint
    n, k = binding.snapshot.prefix, len(layout.states)
    nodes, edges = [], []
    for time in range(n):
        state_rewards = []
        for state in range(k):
            row = []
            for window in layout.windows:
                inside = int(window.left <= time < window.right)
                row.extend(inside * int(state == s) for s in range(k))
                row.append(0)
            state_rewards.append(tuple(row))
        edge = []
        for window in layout.windows:
            edge.extend([0] * k)
            edge.append(int(renewal_belongs_to_window(window, time, n)))
        nodes.append(tuple(state_rewards))
        edges.append(tuple(edge))
    return RewardPlan(binding_fingerprint(binding), layout.states, layout.dimensions,
                      tuple(nodes), tuple(edges))
