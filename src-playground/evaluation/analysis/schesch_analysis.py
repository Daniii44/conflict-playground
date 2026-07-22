import os
from pathlib import Path

from common.evaluation_models import (
    EvaluationInput,
    MergeScheschEvaluation,
)
from common.schesch import DEFAULT_TIMEOUT_SECONDS, ScheschResolutionRunner
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
)


class BaseScheschEvaluationAnalysis(EvaluationAnalysis, ScheschResolutionRunner):
    def __init__(self, analysis_name: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        EvaluationAnalysis.__init__(self, analysis_name)
        ScheschResolutionRunner.__init__(self, timeout_seconds)

    def failed(self, evaluation_input: EvaluationInput, error: str) -> MergeScheschEvaluation:
        return MergeScheschEvaluation(
            resolution_key=evaluation_input.resolution_key,
            actual_resolution_sha=actual_resolution_sha_from_playground_name(
                evaluation_input.restored_playground_name
            ),
            timeout_seconds=self.timeout_seconds,
            error=error,
        )

    def playground_path(self, evaluation_input: EvaluationInput) -> tuple[Path | None, str | None]:
        playgrounds = os.environ.get("PLAYGROUNDS")
        if playgrounds is None:
            return None, "PLAYGROUNDS environment variable is not set"
        return Path(playgrounds) / evaluation_input.restored_playground_name, None
