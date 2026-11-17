from dataclasses import dataclass
from decimal import Decimal, localcontext
from copy import deepcopy
from analysis_tasks.bindings import binding_fingerprint
from run_reports.validation import (validate_result_identity, validate_joint_statistics,
                                    validate_occupancy_conservation)

@dataclass(frozen=True)
class JointRunReport:
    body: dict

    def to_data(self):
        return deepcopy(self.body)

def covariance_from_moments(moments):
    with localcontext() as context:
        context.prec = 70
        return [[float(Decimal(moments.second[i][j])
                       - Decimal(moments.mean[i]) * Decimal(moments.mean[j]))
                 for j in range(len(moments.mean))]
                for i in range(len(moments.mean))]

def assemble_joint_report(binding, layout, moments):
    validate_result_identity(binding, layout, moments)
    mean = [float(x) for x in moments.mean]
    covariance = covariance_from_moments(moments)
    validate_joint_statistics(mean, covariance)
    validate_occupancy_conservation(binding, mean, covariance)
    return JointRunReport({
        "task_id": binding.task_id, "input_id": binding_fingerprint(binding),
        "model_ref": [binding.model_ref.revision_id, binding.model_ref.digest],
        "sequence_ref": [binding.snapshot.sequence_id, binding.snapshot.version],
        "snapshot_id": binding.snapshot.snapshot_id, "prefix": binding.snapshot.prefix,
        "states": list(binding.states),
        "windows": [[w.left, w.right] for w in binding.windows],
        "dimensions": [list(d) for d in layout.dimensions],
        "evidence": moments.evidence.to_data(), "mean": mean, "covariance": covariance})
