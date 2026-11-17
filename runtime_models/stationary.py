from fractions import Fraction
from runtime_models.schema import ModelDefinitionError

class StationaryDistributionError(ModelDefinitionError):
    pass

def segment_stationary_distribution(model):
    n = len(model.states)
    a = [[Fraction(str(p)) for p in row] for row in model.transition]
    rows = [[(a[j][i] if i != j else -sum(a[j][k] for k in range(n) if k != j)) for j in range(n)] + [Fraction(0)]
            for i in range(n - 1)]
    rows.append([Fraction(1)] * n + [Fraction(1)])
    for col in range(n):
        pivot = next((r for r in range(col, n) if rows[r][col]), None)
        if pivot is None:
            raise StationaryDistributionError("stationary equations are singular")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v / divisor for v in rows[col]]
        for r in range(n):
            if r != col:
                multiplier = rows[r][col]
                rows[r] = [x - multiplier * y for x, y in zip(rows[r], rows[col])]
    pi = tuple(row[-1] for row in rows)
    if any(p <= 0 for p in pi):
        raise StationaryDistributionError("stationary mass must be positive")
    for i in range(n):
        residual = sum(pi[j] * a[j][i] for j in range(n)) - pi[i]
        if abs(residual) > Fraction(1, 10**10):
            raise StationaryDistributionError("stationary residual too large")
    return pi

def mean_durations(model):
    return tuple(sum(Fraction(str(p)) * d for d, p in row)
                 for row in model.durations)
