from dataclasses import dataclass
from analysis_tasks.bindings import binding_fingerprint
from joint_inference.moments import GroupRewardPlan

@dataclass(frozen=True)
class GroupWindowLayout:
    device_ids: tuple
    device_states: tuple
    windows: tuple
    dimensions: tuple

def build_group_window_layout(devices, windows):
    dimensions = []
    for number, window in enumerate(windows):
        for device in devices:
            dimensions.extend((number, device.device_id, "occupancy", state)
                              for state in device.states)
            dimensions.append((number, device.device_id, "renewals", ""))
    return GroupWindowLayout(tuple(device.device_id for device in devices),
                             tuple(tuple(device.states) for device in devices),
                             tuple(windows), tuple(dimensions))

def compile_group_reward_plan(binding, layout, phases):
    n, m = binding.prefix, len(layout.dimensions)
    count_a, count_b = (len(states) for states in layout.device_states)
    node_rewards = []
    for time in range(n):
        rows = []
        for phase_a, phase_b in phases:
            row = []
            for window in binding.windows:
                inside = int(window.left <= time < window.right)
                row.extend(inside * int(phase_a.state == state)
                           for state in range(count_a))
                row.append(0)
                row.extend(inside * int(phase_b.state == state)
                           for state in range(count_b))
                row.append(0)
            rows.append(tuple(row))
        node_rewards.append(tuple(rows))
    renewal_a, renewal_b = [], []
    for time in range(n):
        vec_a, vec_b = [], []
        for window in binding.windows:
            paid = int(1 <= time < n and window.left <= time < window.right)
            vec_a.extend([0] * count_a)
            vec_a.append(paid)
            vec_a.extend([0] * count_b)
            vec_a.append(0)
            vec_b.extend([0] * count_a)
            vec_b.append(0)
            vec_b.extend([0] * count_b)
            vec_b.append(paid)
        renewal_a.append(tuple(vec_a))
        renewal_b.append(tuple(vec_b))
    return GroupRewardPlan(binding_fingerprint(binding), layout.device_states,
                           layout.dimensions, tuple(node_rewards),
                           (tuple(renewal_a), tuple(renewal_b)))
