from pydantic import BaseModel, Field

from common.resolution_models import ConflictResolution


class EvaluationInput(BaseModel):
    resolution_key: str
    resolution_postfix: str
    restored_playground_name: str
    resolution: ConflictResolution


class MergeEvaluationRecord(BaseModel):
    resolution_key: str
    error: str | None = None


class MergeCoreEvaluation(MergeEvaluationRecord):
    duration_seconds: float
    incomplete_merge: bool
    perfect_match: bool
    proposed_commit_sha: str | None = None
    actual_resolution_sha: str | None = None


class MergeDiffOutput(BaseModel):
    patch: str | None = None
    raw: str | None = None
    exact_match: bool | None = None


class MergeDiffEvaluation(MergeEvaluationRecord):
    proposed_commit_sha: str | None = None
    actual_resolution_sha: str | None = None
    conflicted_tree_oid: str | None = None
    proposed_to_actual_resolution_diffs: dict[str, dict[str, MergeDiffOutput]] = Field(default_factory=dict)
    conflicted_to_actual_resolution_diffs: dict[str, dict[str, MergeDiffOutput]] = Field(default_factory=dict)
    conflicted_to_proposed_resolution_diffs: dict[str, dict[str, MergeDiffOutput]] = Field(default_factory=dict)
    proposed_to_actual_resolution_patch: str | None = None
    proposed_to_actual_resolution_raw: str | None = None
    conflicted_to_actual_resolution_patch: str | None = None
    conflicted_to_actual_resolution_raw: str | None = None
    conflicted_to_proposed_resolution_patch: str | None = None
    conflicted_to_proposed_resolution_raw: str | None = None


class MergeSummaryEvaluation(MergeEvaluationRecord):
    proposed_commit_sha: str | None = None
    actual_resolution_sha: str | None = None
    conflicted_tree_oid: str | None = None
    info_conflict_key: str | None = None
    judge_model: str | None = None
    original_conflicts: str | None = None
    proposed_to_actual_resolution_patch: str | None = None
    conflicted_to_proposed_resolution_patch: str | None = None
    conflicted_to_actual_resolution_patch: str | None = None
    agent_session: str | None = None
    prompt: str | None = None
    failure_summary: str | None = None


class ScheschCommandResult(BaseModel):
    command: list[str]
    returncode: int | None = None
    timed_out: bool = False
    output_tail: str | None = None


class ScheschJavaAttempt(BaseModel):
    java_home: str
    compile_result: ScheschCommandResult | None = None
    test_result: ScheschCommandResult | None = None


class ScheschResolutionResult(BaseModel):
    label: str
    commit_sha: str | None = None
    build_tool: str | None = None
    passed: bool = False
    compilation_failed: bool = False
    test_execution_failed: bool = False
    timed_out: bool = False
    successful_java_home: str | None = None
    error: str | None = None
    attempts: list[ScheschJavaAttempt] = Field(default_factory=list)


class MergeScheschEvaluation(MergeEvaluationRecord):
    proposed_commit_sha: str | None = None
    actual_resolution_sha: str | None = None
    timeout_seconds: int
    proposed: ScheschResolutionResult | None = None
    human: ScheschResolutionResult | None = None
