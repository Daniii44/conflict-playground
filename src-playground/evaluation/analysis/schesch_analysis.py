import os
from pathlib import Path

from loguru import logger

from common.evaluation_models import (
    EvaluationInput,
    MergeScheschEvaluation,
    ScheschResolutionResult,
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

    def log_analysis_start(self, evaluation_input: EvaluationInput) -> None:
        logger.info(
            "Starting {} evaluation for {} in restored playground {}",
            self.get_analysis_name(),
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
        )

    def log_resolution_result(
        self,
        evaluation_input: EvaluationInput,
        result: ScheschResolutionResult,
    ) -> None:
        logger.info(
            (
                "{} evaluation finished for {} in {}: label={}, commit_sha={}, passed={}, "
                "compilation_failed={}, test_execution_failed={}, timed_out={}, attempts={}"
            ),
            self.get_analysis_name(),
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
            result.label,
            result.commit_sha,
            result.passed,
            result.compilation_failed,
            result.test_execution_failed,
            result.timed_out,
            len(result.attempts),
        )

    def failed(self, evaluation_input: EvaluationInput, error: str) -> MergeScheschEvaluation:
        logger.error(
            "{} evaluation failed for {} in {}: {}",
            self.get_analysis_name(),
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
            error,
        )
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
