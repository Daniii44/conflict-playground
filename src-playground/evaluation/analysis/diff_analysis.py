import os

from common.evaluation_models import EvaluationInput, MergeDiffEvaluation, MergeDiffOutput
from common.git_util import capture_git
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


WHITESPACE_DIFF_MODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exact", ()),
    ("ignore_cr_at_eol", ("--ignore-cr-at-eol",)),
    ("ignore_space_at_eol", ("--ignore-space-at-eol",)),
    ("ignore_space_change", ("--ignore-space-change",)),
    ("ignore_all_space", ("--ignore-all-space",)),
)
BLANK_LINE_DIFF_MODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("include_blank_lines", ()),
    ("ignore_blank_lines", ("--ignore-blank-lines",)),
)
DEFAULT_WHITESPACE_MODE = "exact"
DEFAULT_BLANK_LINE_MODE = "include_blank_lines"


class DiffEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "diff"):
        super().__init__(analysis_name)

    def failed(self, evaluation_input: EvaluationInput, error: str) -> MergeDiffEvaluation:
        return MergeDiffEvaluation(
            resolution_key=evaluation_input.resolution_key,
            actual_resolution_sha=actual_resolution_sha_from_playground_name(
                evaluation_input.restored_playground_name
            ),
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

    def collect_conflicted_tree_oid(
        self,
        playground_path: str,
        left_parent_oid: str,
        right_parent_oid: str,
    ) -> tuple[str | None, str | None]:
        result = capture_git(
            "-C",
            playground_path,
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

        conflicted_tree_oid = result.stdout.split("\0", 1)[0].strip()
        if not conflicted_tree_oid:
            return None, "Could not read conflicted tree oid from merge-tree output"

        return conflicted_tree_oid, None

    def diff_tree(
        self,
        playground_path: str,
        base_ref: str,
        target_ref: str,
        *,
        patch: bool,
        diff_flags: tuple[str, ...] = (),
    ) -> tuple[str | None, str | None]:
        command = [
            "-C",
            playground_path,
            "diff-tree",
            "--color=always",
        ]
        command.extend(diff_flags)
        if patch:
            command.append("-p")
        command.extend([base_ref, target_ref])

        result = capture_git(*command, check=False)
        if result.returncode == 0:
            return result.stdout, None

        error = result.stderr.strip() or result.stdout.strip()
        return None, error

    def collect_diff_matrix(
        self,
        playground_path: str,
        base_ref: str,
        target_ref: str,
    ) -> tuple[dict[str, dict[str, MergeDiffOutput]], str | None]:
        diffs: dict[str, dict[str, MergeDiffOutput]] = {}
        for whitespace_key, whitespace_flags in WHITESPACE_DIFF_MODES:
            diffs[whitespace_key] = {}
            for blank_line_key, blank_line_flags in BLANK_LINE_DIFF_MODES:
                diff_flags = whitespace_flags + blank_line_flags
                patch, diff_error = self.diff_tree(
                    playground_path,
                    base_ref,
                    target_ref,
                    patch=True,
                    diff_flags=diff_flags,
                )
                if diff_error is not None:
                    return diffs, (
                        f"Could not diff {base_ref} against {target_ref} "
                        f"with {whitespace_key}/{blank_line_key} patch: {diff_error}"
                    )

                raw, diff_error = self.diff_tree(
                    playground_path,
                    base_ref,
                    target_ref,
                    patch=False,
                    diff_flags=diff_flags,
                )
                if diff_error is not None:
                    diffs[whitespace_key][blank_line_key] = MergeDiffOutput(patch=patch)
                    return diffs, (
                        f"Could not diff-tree {base_ref} against {target_ref} "
                        f"with {whitespace_key}/{blank_line_key} raw: {diff_error}"
                    )

                diffs[whitespace_key][blank_line_key] = MergeDiffOutput(
                    patch=patch,
                    raw=raw,
                    exact_match=patch == "",
                )

        return diffs, None

    def default_diff_output(self, diffs: dict[str, dict[str, MergeDiffOutput]]) -> MergeDiffOutput:
        return diffs.get(DEFAULT_WHITESPACE_MODE, {}).get(DEFAULT_BLANK_LINE_MODE, MergeDiffOutput())

    def analyse(self, evaluation_input: EvaluationInput) -> MergeDiffEvaluation:
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

        commit_sha, head_error = read_head_commit(playground_path)
        if head_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                actual_resolution_sha=actual_resolution_sha,
                error=head_error,
            )

        proposed_to_actual_diffs, diff_error = self.collect_diff_matrix(
            playground_path,
            "HEAD",
            actual_resolution_sha,
        )
        proposed_to_actual_default = self.default_diff_output(proposed_to_actual_diffs)
        if diff_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                error=f"Could not diff proposed resolution against actual resolution: {diff_error}",
            )

        parents, parents_error = self.collect_parents(playground_path, actual_resolution_sha)
        if parents_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                error=parents_error,
            )

        if len(parents) != 2:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                error=f"Actual resolution has {len(parents)} parents; expected 2",
            )

        conflicted_tree_oid, conflicted_tree_error = self.collect_conflicted_tree_oid(
            playground_path,
            parents[0],
            parents[1],
        )
        if conflicted_tree_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                error=conflicted_tree_error,
            )

        conflicted_to_actual_diffs, diff_error = self.collect_diff_matrix(
            playground_path,
            conflicted_tree_oid,
            actual_resolution_sha,
        )
        conflicted_to_actual_default = self.default_diff_output(conflicted_to_actual_diffs)
        if diff_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                conflicted_tree_oid=conflicted_tree_oid,
                conflicted_to_actual_resolution_diffs=conflicted_to_actual_diffs,
                conflicted_to_actual_resolution_patch=conflicted_to_actual_default.patch,
                conflicted_to_actual_resolution_raw=conflicted_to_actual_default.raw,
                error=f"Could not diff actual resolution against conflicted tree: {diff_error}",
            )

        conflicted_to_proposed_diffs, diff_error = self.collect_diff_matrix(
            playground_path,
            conflicted_tree_oid,
            "HEAD",
        )
        conflicted_to_proposed_default = self.default_diff_output(conflicted_to_proposed_diffs)
        if diff_error is not None:
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
                proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
                proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
                conflicted_tree_oid=conflicted_tree_oid,
                conflicted_to_actual_resolution_diffs=conflicted_to_actual_diffs,
                conflicted_to_actual_resolution_patch=conflicted_to_actual_default.patch,
                conflicted_to_actual_resolution_raw=conflicted_to_actual_default.raw,
                conflicted_to_proposed_resolution_diffs=conflicted_to_proposed_diffs,
                conflicted_to_proposed_resolution_patch=conflicted_to_proposed_default.patch,
                conflicted_to_proposed_resolution_raw=conflicted_to_proposed_default.raw,
                error=f"Could not diff proposed resolution against conflicted tree: {diff_error}",
            )

        return MergeDiffEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
            proposed_to_actual_resolution_diffs=proposed_to_actual_diffs,
            conflicted_to_actual_resolution_diffs=conflicted_to_actual_diffs,
            conflicted_to_proposed_resolution_diffs=conflicted_to_proposed_diffs,
            proposed_to_actual_resolution_patch=proposed_to_actual_default.patch,
            proposed_to_actual_resolution_raw=proposed_to_actual_default.raw,
            conflicted_to_actual_resolution_patch=conflicted_to_actual_default.patch,
            conflicted_to_actual_resolution_raw=conflicted_to_actual_default.raw,
            conflicted_to_proposed_resolution_patch=conflicted_to_proposed_default.patch,
            conflicted_to_proposed_resolution_raw=conflicted_to_proposed_default.raw,
        )
