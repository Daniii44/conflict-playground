import json
import os
import subprocess

from common.evaluation_models import EvaluationInput, MergeSemEvaluation
from common.git_util import git_env
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


class SemEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "sem"):
        super().__init__(analysis_name)

    def failed(self, evaluation_input: EvaluationInput, error: str) -> MergeSemEvaluation:
        return MergeSemEvaluation(
            resolution_key=evaluation_input.resolution_key,
            actual_resolution_sha=actual_resolution_sha_from_playground_name(
                evaluation_input.restored_playground_name
            ),
            error=error,
        )

    def sem_diff(
        self,
        playground_path: str,
        base_ref: str,
        target_ref: str,
    ) -> tuple[dict | None, str | None]:
        result = subprocess.run(
            [
                "sem",
                "diff",
                "--no-cosmetics",
                "--json",
                base_ref,
                target_ref,
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=playground_path,
            env=git_env(),
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return None, error

        try:
            sem_output = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            return None, f"sem returned invalid JSON: {error}"

        if not isinstance(sem_output, dict):
            return None, "sem returned a non-object JSON payload"

        return sem_output, None

    def analyse(self, evaluation_input: EvaluationInput) -> MergeSemEvaluation:
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
            return MergeSemEvaluation(
                resolution_key=evaluation_input.resolution_key,
                actual_resolution_sha=actual_resolution_sha,
                error=head_error,
            )

        sem_output, sem_error = self.sem_diff(
            playground_path,
            "HEAD",
            actual_resolution_sha,
        )
        if sem_error is not None:
            return MergeSemEvaluation(
                resolution_key=evaluation_input.resolution_key,
                proposed_commit_sha=proposed_commit_sha,
                actual_resolution_sha=actual_resolution_sha,
                error=f"Could not compare proposed resolution against actual resolution: {sem_error}",
            )

        return MergeSemEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            proposed_to_actual_sem_diff=sem_output,
        )
