import json
import os
import subprocess
import tempfile
from pathlib import Path

from common.evaluation_models import (
    EvaluationInput,
    MergeConflictResolutionEvaluation,
    MergeConflictResolutionLogicalConflict,
)
from common.git_util import capture_git, capture_git_bytes
from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult, parse_merge_result, prune_auto_merged
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


DEFAULT_ANALYZER_JAR = "tools/conflict-resolution-analyzer-1.0.0.jar"
NOT_IMPLEMENTED_STATUS = "not_implemented"
CLASSIFIED_STATUS = "classified"
ERROR_STATUS = "error"


class ClassificationEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "classification"):
        super().__init__(analysis_name)

    def failed(
        self,
        evaluation_input: EvaluationInput,
        error: str,
        *,
        actual_resolution_sha: str | None = None,
        proposed_commit_sha: str | None = None,
        conflicted_tree_oid: str | None = None,
        logical_conflicts: list[MergeConflictResolutionLogicalConflict] | None = None,
    ) -> MergeConflictResolutionEvaluation:
        return MergeConflictResolutionEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
            logical_conflicts=logical_conflicts or [],
            error=error,
        )

    def collect_parents(self, playground_path: str, merge_commit_oid: str) -> tuple[list[str], str | None]:
        result = capture_git(
            "-C",
            playground_path,
            "show",
            "--no-patch",
            "--format=%P",
            merge_commit_oid,
            check=False,
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
            "-C",
            playground_path,
            "-c",
            "merge.conflictStyle=diff3",
            "merge-tree",
            "-z",
            left_parent_oid,
            right_parent_oid,
            check=False,
        )
        if result.returncode == 0:
            return None, "Actual resolution parents merge cleanly"

        output = result.stdout + result.stderr
        if "fatal: refusing to merge unrelated histories" in output:
            return None, "Actual resolution parents have unrelated histories"

        if not result.stdout:
            return None, "Could not read merge-tree output"

        return prune_auto_merged(parse_merge_result(result.stdout.encode())), None

    def read_blob(self, playground_path: str, ref: str, path: str) -> tuple[bytes | None, str | None]:
        result = capture_git_bytes(
            "-C",
            playground_path,
            "show",
            f"{ref}:{path}",
            check=False,
        )
        if result.returncode == 0:
            return result.stdout, None

        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        error = stderr or stdout
        return None, f"Could not read {path} at {ref}: {error}"

    def analyze_files(self, unmerged_file: Path, merged_file: Path) -> tuple[list[str] | None, str | None]:
        jar_path = os.environ.get("CONFLICT_RESOLUTION_ANALYZER_JAR", DEFAULT_ANALYZER_JAR)
        result = subprocess.run(
            [
                "java",
                "-jar",
                jar_path,
                "--formatting",
                str(unmerged_file),
                str(merged_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return None, f"Conflict resolution analyzer failed: {error}"

        try:
            classifications = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            return None, f"Conflict resolution analyzer returned invalid JSON: {error}"

        if not isinstance(classifications, list) or not all(
            isinstance(classification, str) for classification in classifications
        ):
            return None, "Conflict resolution analyzer returned a non-string classification array"

        return classifications, None

    def classify_resolution(
        self,
        playground_path: str,
        conflicted_tree_oid: str,
        merged_ref: str,
        path: str,
    ) -> tuple[list[str] | None, str | None]:
        unmerged_content, error = self.read_blob(playground_path, conflicted_tree_oid, path)
        if error is not None:
            return None, error

        merged_content, error = self.read_blob(playground_path, merged_ref, path)
        if error is not None:
            return None, error

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            unmerged_file = temp_path / "unmerged"
            merged_file = temp_path / "merged"
            unmerged_file.write_bytes(unmerged_content)
            merged_file.write_bytes(merged_content)
            return self.analyze_files(unmerged_file, merged_file)

    def classify_logical_conflict(
        self,
        playground_path: str,
        conflicted_tree_oid: str,
        actual_resolution_sha: str,
        logical_conflict_index: int,
        logical_conflict: MergeLogicalConflict,
    ) -> MergeConflictResolutionLogicalConflict:
        base = {
            "logical_conflict_index": logical_conflict_index,
            "type": logical_conflict.type,
            "info": logical_conflict.info,
            "paths": logical_conflict.paths,
        }

        if logical_conflict.type != ConflictType.CONFLICT_CONTENTS:
            return MergeConflictResolutionLogicalConflict(
                **base,
                status=NOT_IMPLEMENTED_STATUS,
                error=f"Conflict resolution classification is not implemented for {logical_conflict.type.value}",
            )

        if len(logical_conflict.paths) != 1:
            return MergeConflictResolutionLogicalConflict(
                **base,
                status=ERROR_STATUS,
                error=f"Content conflict has {len(logical_conflict.paths)} paths; expected 1",
            )

        path = logical_conflict.paths[0]
        agent_classifications, agent_error = self.classify_resolution(
            playground_path,
            conflicted_tree_oid,
            "HEAD",
            path,
        )
        human_classifications, human_error = self.classify_resolution(
            playground_path,
            conflicted_tree_oid,
            actual_resolution_sha,
            path,
        )

        errors = [error for error in (agent_error, human_error) if error is not None]
        return MergeConflictResolutionLogicalConflict(
            **base,
            status=ERROR_STATUS if errors else CLASSIFIED_STATUS,
            agent_classifications=agent_classifications,
            human_classifications=human_classifications,
            error="; ".join(errors) if errors else None,
        )

    def analyse(self, evaluation_input: EvaluationInput) -> MergeConflictResolutionEvaluation:
        proposed_resolution = evaluation_input.resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")

        if proposed_resolution.git_archive is None:
            error = proposed_resolution.error or "Resolution has no archived .git repository"
            return self.failed(evaluation_input, error)

        playgrounds = os.environ.get("PLAYGROUNDS")
        if playgrounds is None:
            return self.failed(evaluation_input, "PLAYGROUNDS environment variable is not set")

        playground_name = evaluation_input.restored_playground_name
        playground_path = f"{playgrounds}/{playground_name}"
        actual_resolution_sha = actual_resolution_sha_from_playground_name(playground_name)
        if actual_resolution_sha is None:
            return self.failed(
                evaluation_input,
                f"Could not extract merge SHA from playground name: {playground_name}",
            )

        proposed_commit_sha, head_error = read_head_commit(playground_path)
        if head_error is not None:
            return self.failed(
                evaluation_input,
                head_error,
                actual_resolution_sha=actual_resolution_sha,
            )

        parents, parents_error = self.collect_parents(playground_path, actual_resolution_sha)
        if parents_error is not None:
            return self.failed(
                evaluation_input,
                parents_error,
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=proposed_commit_sha,
            )

        if len(parents) != 2:
            return self.failed(
                evaluation_input,
                f"Actual resolution has {len(parents)} parents; expected 2",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=proposed_commit_sha,
            )

        merge_result, merge_error = self.collect_merge_result(
            playground_path,
            parents[0],
            parents[1],
        )
        if merge_error is not None or merge_result is None:
            return self.failed(
                evaluation_input,
                merge_error or "Could not collect merge-tree result",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=proposed_commit_sha,
            )

        logical_conflicts = [
            self.classify_logical_conflict(
                playground_path,
                merge_result.result_tree_oid,
                actual_resolution_sha,
                index,
                logical_conflict,
            )
            for index, logical_conflict in enumerate(merge_result.logical_conflicts)
        ]

        return MergeConflictResolutionEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=merge_result.result_tree_oid,
            logical_conflicts=logical_conflicts,
        )
