import os

from common.evaluation_models import EvaluationInput, MergeDiffEvaluation
from common.git_util import capture_git
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


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

        diff_result = capture_git(
            "-C",
            playground_path,
            "diff",
            "--color=always",
            "HEAD",
            actual_resolution_sha,
            check=False,
        )
        if diff_result.returncode != 0:
            error = diff_result.stderr.strip() or diff_result.stdout.strip()
            return MergeDiffEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                error=f"Could not diff proposed resolution against actual resolution: {error}",
            )

        return MergeDiffEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            diff_to_actual_resolution=diff_result.stdout,
        )
