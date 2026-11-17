from archive import atomic
from analysis_tasks.requests import (FreezeRequest, InvalidTaskRequest,
                                     validate_freeze_request,
                                     validate_group_freeze_request)
from analysis_tasks.bindings import (TaskBinding, GroupTaskBinding, build_binding,
                                     build_group_binding, binding_fingerprint)
from analysis_tasks.catalog import TaskCatalog
from runtime_models.registry import resolve_model, resolve_group
from observations.sequences import read_sequence_revision
from observations.snapshots import seal_prefix, load_snapshot
from duration_inference.evidence import compute_evidence
from duration_inference.moments import compute_conditional_moments
from joint_inference.kernel import build_joint_kernel
from joint_inference.evidence import compute_joint_evidence
from joint_inference.moments import compute_joint_conditional_moments
from run_reports.windows import build_window_layout, compile_reward_plan
from run_reports.joint import assemble_joint_report
from run_reports.group_windows import build_group_window_layout, compile_group_reward_plan
from run_reports.group_report import assemble_group_report
from run_reports.publication import publish_report, publish_group_report
from run_reports.reader import read_report, read_group_report

class AnalysisExecutionError(RuntimeError):
    pass

def freeze(connection, task_id, model_ref, sequence_revision, prefix, windows):
    request = FreezeRequest(task_id, prefix, tuple(windows))
    with atomic(connection):
        revision = resolve_model(connection, model_ref)
        records = read_sequence_revision(connection, sequence_revision)
        validate_freeze_request(request, len(records))
        snapshot = seal_prefix(connection, sequence_revision, prefix)
        binding = build_binding(request, revision, snapshot)
        return TaskCatalog(connection).freeze_binding(binding)

def analyze(connection, task_id, *, before_commit=None):
    binding, published = TaskCatalog(connection).require_frozen(task_id)
    if isinstance(binding, GroupTaskBinding):
        raise ValueError("task is a group analysis")
    if published is not None:
        return read_report(connection, task_id)
    revision = resolve_model(connection, binding.model_ref)
    snapshot = load_snapshot(connection, binding.snapshot.snapshot_id)
    if snapshot != binding.snapshot or revision.definition.states != binding.states:
        raise AnalysisExecutionError("frozen input integrity failure")
    layout = build_window_layout(binding.states, binding.windows)
    plan = compile_reward_plan(binding, layout)
    trace = compute_evidence(revision.definition, tuple(r.symbol for r in snapshot.records),
                             binding_fingerprint(binding))
    moments = compute_conditional_moments(trace, plan)
    report = assemble_joint_report(binding, layout, moments)
    return publish_report(connection, binding, report, before_commit=before_commit)

def freeze_group(connection, task_id, group_ref, sequences, prefix, windows):
    request = FreezeRequest(task_id, prefix, tuple(windows))
    with atomic(connection):
        group = resolve_group(connection, group_ref)
        if not isinstance(sequences, (list, tuple)) or len(sequences) != 2:
            raise InvalidTaskRequest("exactly two sequence revisions required")
        records = tuple(read_sequence_revision(connection, sequence)
                        for sequence in sequences)
        validate_group_freeze_request(request, tuple(len(r) for r in records))
        times = tuple(tuple(record.time for record in revision[:request.prefix])
                      for revision in records)
        if times[0] != times[1]:
            raise InvalidTaskRequest("prefix observation times differ")
        revisions = tuple(resolve_model(connection, model_ref)
                          for _, model_ref in group.definition.devices)
        snapshots = tuple(seal_prefix(connection, sequence, request.prefix)
                          for sequence in sequences)
        binding = build_group_binding(request, group, revisions, snapshots)
        return TaskCatalog(connection).freeze_binding(binding)

def analyze_group(connection, task_id, *, before_commit=None):
    binding, published = TaskCatalog(connection).require_frozen(task_id)
    if isinstance(binding, TaskBinding):
        raise ValueError("task is a single-device analysis")
    if published is not None:
        return read_group_report(connection, task_id)
    group = resolve_group(connection, binding.group_ref)
    if tuple(group.definition.devices) != tuple(
            (device.device_id, device.model_ref) for device in binding.devices):
        raise AnalysisExecutionError("frozen input integrity failure")
    revisions = tuple(resolve_model(connection, device.model_ref)
                      for device in binding.devices)
    snapshots = tuple(load_snapshot(connection, device.snapshot.snapshot_id)
                      for device in binding.devices)
    if (any(snapshot != device.snapshot
            for snapshot, device in zip(snapshots, binding.devices))
            or any(revision.definition.states != device.states
                   for revision, device in zip(revisions, binding.devices))):
        raise AnalysisExecutionError("frozen input integrity failure")
    layout = build_group_window_layout(binding.devices, binding.windows)
    kernel = build_joint_kernel(tuple(revision.definition for revision in revisions),
                                group.definition.shock_probs)
    plan = compile_group_reward_plan(binding, layout, kernel.phases)
    symbols = tuple(tuple(record.symbol for record in snapshot.records)
                    for snapshot in snapshots)
    trace = compute_joint_evidence(kernel, symbols, binding_fingerprint(binding))
    moments = compute_joint_conditional_moments(trace, plan)
    report = assemble_group_report(binding, layout, moments)
    return publish_group_report(connection, binding, report, before_commit=before_commit)
