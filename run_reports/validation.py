import math
from analysis_tasks.bindings import binding_fingerprint

class ReportValidationError(ValueError):
    pass

def validate_result_identity(binding, layout, moments):
    if (moments.input_id != binding_fingerprint(binding)
            or moments.states != binding.states or layout.states != binding.states
            or layout.windows != binding.windows
            or moments.dimensions != layout.dimensions):
        raise ReportValidationError("result input or dimension identity mismatch")
    m = len(layout.dimensions)
    if len(moments.mean) != m or len(moments.second) != m:
        raise ReportValidationError("moment shape")
    if any(len(row) != m for row in moments.second):
        raise ReportValidationError("second moment shape")
    for row in (moments.mean, *moments.second):
        if any(not math.isfinite(x) for x in row):
            raise ReportValidationError("nonfinite moments")
    evidence = moments.evidence
    if not math.isfinite(evidence.log_evidence):
        raise ReportValidationError("nonfinite evidence")
    try:
        from decimal import Decimal
        mantissa = Decimal(evidence.mantissa)
        if not mantissa.is_finite() or not 1 <= mantissa < 10:
            raise ReportValidationError("invalid evidence mantissa")
    except (ValueError, ArithmeticError) as error:
        raise ReportValidationError("invalid evidence representation") from error
    if type(evidence.exponent) is not int:
        raise ReportValidationError("invalid evidence exponent")
    if evidence.probability is not None and (
            not math.isfinite(evidence.probability) or evidence.probability <= 0):
        raise ReportValidationError("invalid positive evidence")

def validate_joint_statistics(mean, covariance):
    m = len(mean)
    if len(covariance) != m or any(len(row) != m for row in covariance):
        raise ReportValidationError("covariance shape")
    if any(not math.isfinite(x) for row in (mean, *covariance) for x in row):
        raise ReportValidationError("nonfinite joint statistics")
    for i in range(m):
        if covariance[i][i] < -1e-8:
            raise ReportValidationError("negative variance")
        for j in range(m):
            if abs(covariance[i][j] - covariance[j][i]) > 1e-8:
                raise ReportValidationError("asymmetric covariance")

def validate_occupancy_conservation(binding, mean, covariance):
    k = len(binding.states)
    for number, window in enumerate(binding.windows):
        offset, length = number * (k + 1), window.right - window.left
        if abs(math.fsum(mean[offset:offset+k]) - length) > 1e-8:
            raise ReportValidationError("occupancy mean conservation")
        for state in range(k):
            if not -1e-8 <= mean[offset+state] <= length + 1e-8:
                raise ReportValidationError("occupancy outside bounds")
        for j in range(len(mean)):
            if abs(math.fsum(covariance[offset+s][j] for s in range(k))) > 1e-8:
                raise ReportValidationError("occupancy covariance conservation")
        maximum = max(0, min(window.right, binding.snapshot.prefix) - max(1, window.left))
        if not -1e-8 <= mean[offset+k] <= maximum + 1e-8:
            raise ReportValidationError("renewal mean outside bounds")
        if length == 0:
            for i in range(offset, offset+k+1):
                if abs(mean[i]) > 1e-8 or any(abs(x) > 1e-8 for x in covariance[i]):
                    raise ReportValidationError("empty window is not deterministic zero")
