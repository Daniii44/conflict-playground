from pydantic import BaseModel

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


class MergeDiffEvaluation(MergeEvaluationRecord):
    proposed_commit_sha: str | None = None
    actual_resolution_sha: str | None = None
    conflicted_tree_oid: str | None = None
    proposed_to_actual_resolution_patch: str | None = None
    proposed_to_actual_resolution_raw: str | None = None
    conflicted_to_actual_resolution_patch: str | None = None
    conflicted_to_actual_resolution_raw: str | None = None
    conflicted_to_proposed_resolution_patch: str | None = None
    conflicted_to_proposed_resolution_raw: str | None = None
