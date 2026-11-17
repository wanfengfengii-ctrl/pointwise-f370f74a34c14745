from fractions import Fraction as F

def enumerate_paths(model, symbols, windows):
    n, k = len(symbols), len(model.states)
    if k == 1:
        pi = [F(1)]
    elif k == 2:
        ab, ba = F(str(model.transition[0][1])), F(str(model.transition[1][0]))
        pi = [ba / (ab + ba), ab / (ab + ba)]
    else:
        raise ValueError("oracle supports only one or two states")
    duration = [[(d, F(str(p))) for d, p in row] for row in model.durations]
    emission = [dict((symbol, F(str(p))) for symbol, p in row) for row in model.emissions]
    mean_length = sum(pi[s] * sum(d * p for d, p in duration[s]) for s in range(k))
    m = len(windows) * (k + 1)
    evidence, first = F(0), [F(0)] * m
    second = [[F(0)] * m for _ in range(m)]

    def finish(states, starts, mass):
        nonlocal evidence
        vector = []
        for window in windows:
            vector.extend(sum(states[t] == s for t in range(window.left, window.right))
                          for s in range(k))
            vector.append(sum(window.left <= t < window.right for t in starts))
        evidence += mass
        for i, x in enumerate(vector):
            first[i] += mass * x
            for j, y in enumerate(vector):
                second[i][j] += mass * x * y

    def visit(time, state, remaining, mass, states, starts):
        mass *= emission[state].get(symbols[time], F(0))
        if mass == 0:
            return
        states = states + [state]
        if time + 1 == n:
            finish(states, starts, mass)
        elif remaining > 1:
            visit(time + 1, state, remaining - 1, mass, states, starts)
        else:
            for target, transition in enumerate(model.transition[state]):
                for length, probability in duration[target]:
                    visit(time + 1, target, length,
                          mass * F(str(transition)) * probability,
                          states, starts + [time + 1])
    if not n:
        finish([], [], F(1))
    else:
        for state in range(k):
            for length, probability in duration[state]:
                for age in range(length):
                    visit(0, state, length - age,
                          pi[state] * probability / mean_length, [], [])
    if not evidence:
        return evidence, None, None
    mean = [x / evidence for x in first]
    covariance = [[second[i][j] / evidence - mean[i] * mean[j] for j in range(m)]
                  for i in range(m)]
    return evidence, mean, covariance

def assert_report(test, report, expected):
    evidence, mean, covariance = expected
    test.assertAlmostEqual(report["evidence"]["probability"], float(evidence), delta=1e-8)
    test.assertEqual(len(report["mean"]), len(mean))
    for actual, value in zip(report["mean"], mean):
        test.assertAlmostEqual(actual, float(value), delta=1e-8,
                               msg="RENEWAL_MOMENT_MISMATCH")
    for actual_row, row in zip(report["covariance"], covariance):
        test.assertEqual(len(actual_row), len(row))
        for actual, value in zip(actual_row, row):
            test.assertAlmostEqual(actual, float(value), delta=1e-8,
                                   msg="RENEWAL_MOMENT_MISMATCH")
