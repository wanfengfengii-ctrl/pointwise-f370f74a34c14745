from archive import atomic
from analysis_tasks.requests import FreezeRequest, validate_freeze_request
from analysis_tasks.bindings import build_binding, binding_fingerprint
from analysis_tasks.catalog import TaskCatalog
from runtime_models.registry import resolve_model
from observations.sequences import read_sequence_revision
from observations.snapshots import seal_prefix, load_snapshot
from duration_inference.evidence import compute_evidence
from duration_inference.moments import compute_conditional_moments
from run_reports.windows import build_window_layout, compile_reward_plan
from run_reports.joint import assemble_joint_report
from run_reports.publication import publish_report
from run_reports.reader import read_report

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
