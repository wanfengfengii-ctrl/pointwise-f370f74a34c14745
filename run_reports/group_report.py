from analysis_tasks.bindings import binding_fingerprint
from run_reports.joint import JointRunReport, covariance_from_moments
from run_reports.validation import (validate_group_result_identity,
                                    validate_joint_statistics,
                                    validate_group_occupancy_conservation)

def assemble_group_report(binding, layout, moments):
    validate_group_result_identity(binding, layout, moments)
    mean = [float(x) for x in moments.mean]
    covariance = covariance_from_moments(moments)
    validate_joint_statistics(mean, covariance)
    validate_group_occupancy_conservation(binding, mean, covariance)
    return JointRunReport({
        "task_id": binding.task_id, "input_id": binding_fingerprint(binding),
        "group_ref": [binding.group_ref.revision_id, binding.group_ref.digest],
        "devices": [device.report_data() for device in binding.devices],
        "prefix": binding.prefix,
        "windows": [[w.left, w.right] for w in binding.windows],
        "dimensions": [list(d) for d in layout.dimensions],
        "evidence": moments.evidence.to_data(), "mean": mean, "covariance": covariance})
