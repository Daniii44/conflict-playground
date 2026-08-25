import os

from pydantic import BaseModel

from common.evaluation_models import (
    EvaluationInput,
    MergeModifyDeleteEvaluation,
    ModifyDeletePathEvaluation,
)
from common.git_util import capture_git
from common.merge_tree import ConflictType, MergeConflictedFile, MergeResult, parse_merge_result, prune_auto_merged
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


CANONICAL_BASE = "canonical base"
CANONICAL_KEEP = "canonical keep"
CANONICAL_DELETE = "canonical delete"
NONCANONICAL = "noncanonical"
CANONICAL_CONTRADICTION = "canonical contradiction"
NONCANONICAL_FALLBACK = "non-canonical fallback"
CANONICAL_CLASSIFICATIONS = {CANONICAL_BASE, CANONICAL_KEEP, CANONICAL_DELETE}


class ModifyDeleteConflictPath(BaseModel):
    logical_conflict_index: int
    path: str
    base_oid: str | None = None
    ours_oid: str | None = None
    theirs_oid: str | None = None


class ModifyDeleteEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "modifydelete"):
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
    def extract_conflicts(merge_result: MergeResult) -> list[ModifyDeleteConflictPath]:
        files_by_path: dict[str, list[MergeConflictedFile]] = {}
        for file in merge_result.conflicted_files:
            files_by_path.setdefault(file.path, []).append(file)

        conflicts = []
        for index, logical_conflict in enumerate(merge_result.logical_conflicts):
            if logical_conflict.type != ConflictType.CONFLICT_MODIFY_DELETE:
                continue
            for path in logical_conflict.paths:
                stage_oids = {file.stage: file.oid for file in files_by_path.get(path, [])}
                conflicts.append(
                    ModifyDeleteConflictPath(
                        logical_conflict_index=index,
                        path=path,
                        base_oid=stage_oids.get(1),
                        ours_oid=stage_oids.get(2),
                        theirs_oid=stage_oids.get(3),
                    )
                )
        return conflicts

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

    @staticmethod
    def contradiction(agent_classification: str, human_classification: str) -> str | None:
        agent_is_canonical = agent_classification in CANONICAL_CLASSIFICATIONS
        human_is_canonical = human_classification in CANONICAL_CLASSIFICATIONS
        if agent_is_canonical and human_is_canonical:
            return (
                CANONICAL_CONTRADICTION
                if agent_classification != human_classification
                else None
            )
        if agent_is_canonical != human_is_canonical:
            return NONCANONICAL_FALLBACK
        return None

    def failed(
        self,
        evaluation_input: EvaluationInput,
        error: str,
        *,
        proposed_commit_sha: str | None = None,
        actual_resolution_sha: str | None = None,
        conflicted_tree_oid: str | None = None,
    ) -> MergeModifyDeleteEvaluation:
        return MergeModifyDeleteEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
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
            agent_oid, agent_error = self.tree_oid_for_path(playground_path, "HEAD", conflict.path)
            human_oid, human_error = self.tree_oid_for_path(playground_path, actual_resolution_sha, conflict.path)
            if agent_error is not None or human_error is not None:
                errors = [error for error in (agent_error, human_error) if error is not None]
                return self.failed(evaluation_input, "; ".join(errors), proposed_commit_sha=proposed_commit_sha, actual_resolution_sha=actual_resolution_sha, conflicted_tree_oid=merge_result.result_tree_oid)
            agent_classification = self.classify(agent_oid, conflict)
            human_classification = self.classify(human_oid, conflict)
            path_evaluations.append(
                ModifyDeletePathEvaluation(
                    logical_conflict_index=conflict.logical_conflict_index,
                    path=conflict.path,
                    agent_classification=agent_classification,
                    human_classification=human_classification,
                    contradiction=self.contradiction(agent_classification, human_classification),
                )
            )

        return MergeModifyDeleteEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=merge_result.result_tree_oid,
            path_evaluations=path_evaluations,
        )
