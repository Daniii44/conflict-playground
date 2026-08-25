import os

from pydantic import BaseModel

from common.evaluation_models import EvaluationInput, MergeRenameEvaluation, RenamePathEvaluation
from common.git_util import capture_git
from common.merge_tree import ConflictType, MergeResult, parse_merge_result, prune_auto_merged
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


RENAME_CONFLICT_TYPES = {
    ConflictType.CONFLICT_DIR_RENAME_SUGGESTED,
    ConflictType.CONFLICT_RENAME_DELETE,
    ConflictType.CONFLICT_RENAME_RENAME,
    ConflictType.CONFLICT_DIR_RENAME_SPLIT,
}


class RenameConflictPath(BaseModel):
    logical_conflict_index: int
    path: str


class RenameEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "rename"):
        super().__init__(analysis_name)

    def collect_parents(self, playground_path: str, merge_commit_oid: str) -> tuple[list[str], str | None]:
        result = capture_git(
            "-C", playground_path, "show", "--no-patch", "--format=%P", merge_commit_oid, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip().split(), None
        error = result.stderr.strip() or result.stdout.strip()
        return [], f"Could not read actual resolution parents: {error}"

    def collect_merge_result(
        self,
        playground_path: str,
        left_parent_oid: str,
        right_parent_oid: str,
    ) -> tuple[MergeResult | None, str | None]:
        result = capture_git(
            "-C", playground_path, "merge-tree", "-z", left_parent_oid, right_parent_oid, check=False
        )
        if result.returncode == 0:
            return None, "Actual resolution parents merge cleanly"
        output = result.stdout + result.stderr
        if "fatal: refusing to merge unrelated histories" in output:
            return None, "Actual resolution parents have unrelated histories"
        if not result.stdout:
            return None, "Could not read merge-tree output"
        return prune_auto_merged(parse_merge_result(result.stdout.encode())), None

    @staticmethod
    def extract_conflicts(merge_result: MergeResult) -> list[RenameConflictPath]:
        return [
            RenameConflictPath(logical_conflict_index=index, path=path)
            for index, logical_conflict in enumerate(merge_result.logical_conflicts)
            if logical_conflict.type in RENAME_CONFLICT_TYPES
            for path in logical_conflict.paths
        ]

    def path_exists(
        self,
        playground_path: str,
        ref: str,
        path: str,
    ) -> tuple[bool | None, str | None]:
        result = capture_git(
            "-C", playground_path, "ls-tree", "--name-only", "-z", ref, "--", path, check=False
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return None, f"Could not inspect {path} at {ref}: {error}"
        return bool(result.stdout), None

    def failed(
        self,
        evaluation_input: EvaluationInput,
        error: str,
        *,
        proposed_commit_sha: str | None = None,
        actual_resolution_sha: str | None = None,
        conflicted_tree_oid: str | None = None,
    ) -> MergeRenameEvaluation:
        return MergeRenameEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
            error=error,
        )

    def analyse(self, evaluation_input: EvaluationInput) -> MergeRenameEvaluation:
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

        parents, parents_error = self.collect_parents(playground_path, actual_resolution_sha)
        if parents_error is not None:
            return self.failed(evaluation_input, parents_error, proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha)
        if len(parents) != 2:
            return self.failed(evaluation_input, f"Actual resolution has {len(parents)} parents; expected 2", proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha)
        merge_result, merge_error = self.collect_merge_result(playground_path, parents[0], parents[1])
        if merge_error is not None or merge_result is None:
            return self.failed(evaluation_input, merge_error or "Could not collect merge-tree result", proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha)

        path_evaluations = []
        for conflict in self.extract_conflicts(merge_result):
            agent_present, agent_error = self.path_exists(playground_path, "HEAD", conflict.path)
            human_present, human_error = self.path_exists(playground_path, actual_resolution_sha, conflict.path)
            if agent_error is not None or human_error is not None:
                errors = [error for error in (agent_error, human_error) if error is not None]
                return self.failed(evaluation_input, "; ".join(errors), proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha, conflicted_tree_oid=merge_result.result_tree_oid)
            assert agent_present is not None and human_present is not None
            path_evaluations.append(
                RenamePathEvaluation(
                    logical_conflict_index=conflict.logical_conflict_index,
                    path=conflict.path,
                    agent_present=agent_present,
                    human_present=human_present,
                    contradiction=agent_present != human_present,
                )
            )

        return MergeRenameEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=merge_result.result_tree_oid,
            path_evaluations=path_evaluations,
        )
