import os
import subprocess
from datetime import datetime

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput, MergeCoreEvaluation
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


def evaluation_check_for_merge(playground_name: str) -> bool:
    """Check if all commits can be merged without conflicts."""
    try:
        subprocess.run(["evaluation-check-for-merge", playground_name], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def evaluation_diff(playground_name: str) -> bool:
    """Check if there are any differences in the merged result."""
    try:
        subprocess.run(["evaluation-diff", playground_name], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def duration_seconds(configuration: Configuration, resolution_end: datetime) -> float:
    resolution_start = configuration.resolution_start
    if resolution_start.tzinfo is not None and resolution_end.tzinfo is None:
        resolution_end = resolution_end.replace(tzinfo=resolution_start.tzinfo)
    if resolution_start.tzinfo is None and resolution_end.tzinfo is not None:
        resolution_start = resolution_start.replace(tzinfo=resolution_end.tzinfo)

    return (resolution_end - resolution_start).total_seconds()


class CoreEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "core"):
        super().__init__(analysis_name)

    def failed(self, evaluation_input: EvaluationInput, error: str) -> MergeCoreEvaluation:
        resolution = evaluation_input.resolution
        return MergeCoreEvaluation(
            resolution_key=evaluation_input.resolution_key,
            duration_seconds=duration_seconds(
                resolution.configuration,
                resolution.resolution_end,
            ),
            incomplete_merge=True,
            perfect_match=False,
            actual_resolution_sha=actual_resolution_sha_from_playground_name(
                evaluation_input.restored_playground_name
            ),
            error=error,
        )

    def analyse(self, evaluation_input: EvaluationInput) -> MergeCoreEvaluation:
        resolution = evaluation_input.resolution
        proposed_resolution = resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")

        if proposed_resolution.git_archive is None:
            error = proposed_resolution.error or "Resolution has no archived .git repository"
            return self.failed(evaluation_input, error)

        playground_name = evaluation_input.restored_playground_name
        playgrounds = os.environ.get("PLAYGROUNDS")
        playground_path = f"{playgrounds}/{playground_name}" if playgrounds is not None else playground_name
        proposed_commit_sha, head_error = read_head_commit(playground_path)
        actual_resolution_sha = actual_resolution_sha_from_playground_name(playground_name)

        record = MergeCoreEvaluation(
            resolution_key=evaluation_input.resolution_key,
            duration_seconds=duration_seconds(
                resolution.configuration,
                resolution.resolution_end,
            ),
            incomplete_merge=False,
            perfect_match=False,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            error=head_error,
        )

        if not evaluation_check_for_merge(playground_name):
            record.incomplete_merge = True
            return record

        if not evaluation_diff(playground_name):
            record.perfect_match = False
            return record

        record.perfect_match = True
        return record
