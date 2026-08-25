import os

from common.evaluation_models import (
    EvaluationInput,
    MergeModifyDeleteEvaluation,
    ModifyDeletePathEvaluation,
)
from common.git_util import capture_git
from common.redis_util import setup_redis_connection
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)
from info.conflict.analysis.modifydelete_analysis import InfoConflictModifyDelete, ModifyDeleteConflictPath


CANONICAL_BASE = "canonical base"
CANONICAL_KEEP = "canonical keep"
CANONICAL_DELETE = "canonical delete"
NONCANONICAL = "noncanonical"


class ModifyDeleteEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "modifydelete", redis_client=None):
        super().__init__(analysis_name)
        self._redis = redis_client

    def redis_connection(self):
        if self._redis is None:
            self._redis = setup_redis_connection()
        return self._redis

    @staticmethod
    def repo_and_merge_from_resolution(evaluation_input: EvaluationInput) -> tuple[str, str | None]:
        playground_name = evaluation_input.resolution_postfix.rsplit(":", 1)[0]
        if "-" not in playground_name:
            return playground_name, None
        return playground_name.rsplit("-", 1)

    def info_conflict_key(self, evaluation_input: EvaluationInput) -> str | None:
        repo_name, merge_sha = self.repo_and_merge_from_resolution(evaluation_input)
        if merge_sha is None:
            return None
        return f"info:conflict:modifydelete:{repo_name}:{merge_sha}"

    def read_info_conflict(
        self,
        evaluation_input: EvaluationInput,
    ) -> tuple[InfoConflictModifyDelete | None, str | None, str | None]:
        key = self.info_conflict_key(evaluation_input)
        if key is None:
            return None, None, "Could not determine repository and merge SHA from resolution key"
        payload = self.redis_connection().json().get(key)
        if payload is None:
            return None, key, f"No corresponding modify/delete info analysis data at {key}"
        return InfoConflictModifyDelete.model_validate(payload), key, None

    def tree_oid_for_path(
        self,
        playground_path: str,
        ref: str,
        path: str,
    ) -> tuple[str | None, str | None]:
        result = capture_git("-C", playground_path, "ls-tree", "-z", ref, "--", path, check=False)
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return None, f"Could not inspect {path} at {ref}: {error}"
        if not result.stdout:
            return None, None

        entry = result.stdout.split("\0", 1)[0]
        metadata, separator, entry_path = entry.partition("\t")
        parts = metadata.split()
        if separator != "\t" or entry_path != path or len(parts) != 3:
            return None, f"Could not parse ls-tree entry for {path} at {ref}"
        return parts[2], None

    @staticmethod
    def classify(oid: str | None, conflict: ModifyDeleteConflictPath) -> str:
        if oid is None:
            return CANONICAL_DELETE
        if oid == conflict.base_oid:
            return CANONICAL_BASE
        if oid == conflict.ours_oid or oid == conflict.theirs_oid:
            return CANONICAL_KEEP
        return NONCANONICAL

    def failed(
        self,
        evaluation_input: EvaluationInput,
        error: str,
        *,
        proposed_commit_sha: str | None = None,
        actual_resolution_sha: str | None = None,
        info_conflict_key: str | None = None,
    ) -> MergeModifyDeleteEvaluation:
        return MergeModifyDeleteEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            info_conflict_key=info_conflict_key,
            error=error,
        )

    def analyse(self, evaluation_input: EvaluationInput) -> MergeModifyDeleteEvaluation:
        proposed_resolution = evaluation_input.resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")
        if proposed_resolution.git_archive is None:
            return self.failed(evaluation_input, proposed_resolution.error or "Resolution has no archived .git repository")

        actual_resolution_sha = actual_resolution_sha_from_playground_name(evaluation_input.restored_playground_name)
        if actual_resolution_sha is None:
            return self.failed(evaluation_input, "Could not extract merge SHA from playground name")
        playgrounds = os.environ.get("PLAYGROUNDS")
        if playgrounds is None:
            return self.failed(evaluation_input, "PLAYGROUNDS environment variable is not set", actual_resolution_sha=actual_resolution_sha)
        playground_path = f"{playgrounds}/{evaluation_input.restored_playground_name}"
        proposed_commit_sha, head_error = read_head_commit(playground_path)
        if head_error is not None:
            return self.failed(evaluation_input, head_error, actual_resolution_sha=actual_resolution_sha)

        info, info_key, info_error = self.read_info_conflict(evaluation_input)
        if info_error is not None or info is None:
            return self.failed(evaluation_input, info_error or "Could not load modify/delete info analysis", proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha, info_conflict_key=info_key)

        path_evaluations = []
        for conflict in info.conflicts:
            agent_oid, agent_error = self.tree_oid_for_path(playground_path, "HEAD", conflict.path)
            human_oid, human_error = self.tree_oid_for_path(playground_path, actual_resolution_sha, conflict.path)
            if agent_error is not None or human_error is not None:
                errors = [error for error in (agent_error, human_error) if error is not None]
                return self.failed(evaluation_input, "; ".join(errors), proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha, info_conflict_key=info_key)
            path_evaluations.append(
                ModifyDeletePathEvaluation(
                    logical_conflict_index=conflict.logical_conflict_index,
                    path=conflict.path,
                    agent_classification=self.classify(agent_oid, conflict),
                    human_classification=self.classify(human_oid, conflict),
                )
            )

        return MergeModifyDeleteEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            info_conflict_key=info_key,
            path_evaluations=path_evaluations,
        )
