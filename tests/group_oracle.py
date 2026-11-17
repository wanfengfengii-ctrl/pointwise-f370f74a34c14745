"""Independent Fraction enumeration for two-device shock groups.

Does not call any production joint inference code: the joint stationary
initial phases, shock subsets, per-device transition/duration draws and
emissions are enumerated directly, weighted by all frozen observations,
and the full reward vector and its outer product are accumulated exactly.
"""
from decimal import Decimal, localcontext
from fractions import Fraction as F


def _normalized(values):
    values = [F(str(value)) for value in values]
    total = sum(values, F(0))
    return [value / total for value in values]


def _device_tables(model):
    transition = [_normalized(row) for row in model.transition]
    durations = []
    for row in model.durations:
        probs = _normalized([p for _, p in row])
        durations.append(list(zip([key for key, _ in row], probs)))
    emissions = []
    for row in model.emissions:
        probs = _normalized([p for _, p in row])
        emissions.append(dict(zip([key for key, _ in row], probs)))
    phases = tuple((state, remaining)
                   for state in range(len(model.states))
                   for remaining in range(1, max(d for d, _ in model.durations[state]) + 1))
    return {"transition": transition, "durations": durations,
            "emissions": emissions, "phases": phases}


def _branches(device, phase, shocked):
    state, remaining = phase
    if remaining == 1 or shocked:
        out = []
        for target, probability in enumerate(device["transition"][state]):
            if probability > 0:
                for length, mass in device["durations"][target]:
                    if mass > 0:
                        out.append(((target, length), probability * mass, True))
        return tuple(out)
    return (((state, remaining - 1), F(1), False),)


def _joint_stationary(devices, shock):
    phases_a, phases_b = devices[0]["phases"], devices[1]["phases"]
    joints = tuple((pa, pb) for pa in phases_a for pb in phases_b)
    index = {phase: i for i, phase in enumerate(joints)}
    count = len(joints)
    kernel = [[F(0)] * count for _ in range(count)]
    for i, (pa, pb) in enumerate(joints):
        acc = {}
        for subset in range(4):
            weight = shock[subset]
            if not weight:
                continue
            for ta, prob_a, _ in _branches(devices[0], pa, subset in (1, 3)):
                for tb, prob_b, _ in _branches(devices[1], pb, subset in (2, 3)):
                    j = index[(ta, tb)]
                    acc[j] = acc.get(j, F(0)) + weight * prob_a * prob_b
        for j, probability in acc.items():
            kernel[i][j] += probability
    rows = []
    for col in range(count):
        rows.append([kernel[r][col] - (1 if r == col else 0)
                     for r in range(count)] + [F(0)])
    rows.append([F(1)] * count + [F(1)])
    for col in range(count):
        pivot = next((r for r in range(col, count + 1) if rows[r][col]), None)
        if pivot is None:
            raise ValueError("oracle: joint stationary distribution is not unique")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [value / divisor for value in rows[col]]
        for r in range(count + 1):
            if r != col and rows[r][col]:
                multiplier = rows[r][col]
                rows[r] = [x - multiplier * y for x, y in zip(rows[r], rows[col])]
    return tuple(rows[r][-1] for r in range(count)), joints


def enumerate_group_paths(models, shock_probs, symbols_pair, windows):
    devices = (_device_tables(models[0]), _device_tables(models[1]))
    shock = _normalized(shock_probs)
    sym_a, sym_b = tuple(symbols_pair[0]), tuple(symbols_pair[1])
    n = len(sym_a)
    stationary, joints = _joint_stationary(devices, shock)
    count_a, count_b = len(models[0].states), len(models[1].states)
    m = len(windows) * (count_a + 1 + count_b + 1)
    evidence = F(0)
    first = [F(0)] * m
    second = [[F(0)] * m for _ in range(m)]

    def finish(mass, states_a, states_b, starts_a, starts_b):
        nonlocal evidence
        vector = []
        for window in windows:
            vector.extend(sum(1 for t in range(window.left, window.right)
                              if states_a[t] == s) for s in range(count_a))
            vector.append(sum(1 for t in starts_a if window.left <= t < window.right))
            vector.extend(sum(1 for t in range(window.left, window.right)
                              if states_b[t] == s) for s in range(count_b))
            vector.append(sum(1 for t in starts_b if window.left <= t < window.right))
        evidence += mass
        for i, x in enumerate(vector):
            first[i] += mass * x
            for j, y in enumerate(vector):
                second[i][j] += mass * x * y

    def visit(time, pa, pb, mass, states_a, states_b, starts_a, starts_b):
        emit_a = devices[0]["emissions"][pa[0]].get(sym_a[time], F(0))
        emit_b = devices[1]["emissions"][pb[0]].get(sym_b[time], F(0))
        mass = mass * emit_a * emit_b
        if not mass:
            return
        states_a = states_a + (pa[0],)
        states_b = states_b + (pb[0],)
        if time + 1 == n:
            finish(mass, states_a, states_b, starts_a, starts_b)
            return
        for subset in range(4):
            weight = shock[subset]
            if not weight:
                continue
            for ta, prob_a, renewal_a in _branches(devices[0], pa, subset in (1, 3)):
                for tb, prob_b, renewal_b in _branches(devices[1], pb, subset in (2, 3)):
                    visit(time + 1, ta, tb, mass * weight * prob_a * prob_b,
                          states_a, states_b,
                          starts_a + ((time + 1,) if renewal_a else ()),
                          starts_b + ((time + 1,) if renewal_b else ()))

    if n == 0:
        finish(F(1), (), (), (), ())
    else:
        for (pa, pb), mass in zip(joints, stationary):
            if mass:
                visit(0, pa, pb, mass, (), (), (), ())
    if not evidence:
        return evidence, None, None
    mean = [x / evidence for x in first]
    covariance = [[second[i][j] / evidence - mean[i] * mean[j] for j in range(m)]
                  for i in range(m)]
    return evidence, mean, covariance


def log_fraction(value):
    with localcontext() as context:
        context.prec = 50
        return float((Decimal(value.numerator) / Decimal(value.denominator)).ln())


def assert_group_report(test, report, expected):
    evidence, mean, covariance = expected
    if report["evidence"]["probability"] is not None:
        test.assertAlmostEqual(report["evidence"]["probability"], float(evidence),
                               delta=1e-8)
    test.assertAlmostEqual(report["evidence"]["log_evidence"], log_fraction(evidence),
                           delta=1e-8)
    test.assertEqual(len(report["mean"]), len(mean))
    for actual, value in zip(report["mean"], mean):
        test.assertAlmostEqual(actual, float(value), delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
    for actual_row, row in zip(report["covariance"], covariance):
        test.assertEqual(len(actual_row), len(row))
        for actual, value in zip(actual_row, row):
            test.assertAlmostEqual(actual, float(value), delta=1e-8,
                                   msg="RENEWAL_MOMENT_MISMATCH")
