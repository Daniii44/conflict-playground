import os
from pathlib import Path

from loguru import logger

from common.evaluation_models import (
    EvaluationInput,
    MergeScheschEvaluation,
    ScheschCommandResult,
    ScheschJavaAttempt,
    ScheschResolutionResult,
)
from common.redis_util import setup_redis_connection
from common.schesch import (
    DEFAULT_TIMEOUT_SECONDS,
    ScheschResolutionRunner,
    determine_expected_java_home,
    parse_schesch_playground_name,
    schesch_info_key,
)
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
        for attempt_index, attempt in enumerate(result.attempts, start=1):
            self.log_java_attempt(evaluation_input, attempt_index, attempt)

    def log_java_attempt(
        self,
        evaluation_input: EvaluationInput,
        attempt_index: int,
        attempt: ScheschJavaAttempt,
    ) -> None:
        logger.info(
            "{} evaluation Java attempt {} for {} in {} used {}",
            self.get_analysis_name(),
            attempt_index,
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
            attempt.java_home,
        )
        self.log_command_result(evaluation_input, attempt_index, "compile", attempt.compile_result)
        self.log_command_result(evaluation_input, attempt_index, "test", attempt.test_result)

    def log_command_result(
        self,
        evaluation_input: EvaluationInput,
        attempt_index: int,
        phase: str,
        command_result: ScheschCommandResult | None,
    ) -> None:
        if command_result is None:
            return

        logger.info(
            "{} evaluation {} attempt {} for {} in {}: command={}, returncode={}, timed_out={}, duration_seconds={}",
            self.get_analysis_name(),
            phase,
            attempt_index,
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
            command_result.command,
            command_result.returncode,
            command_result.timed_out,
            command_result.duration_seconds,
        )
        if not command_result.output_tail:
            return

        log_output = logger.warning if command_result.timed_out or command_result.returncode not in (None, 0) else logger.info
        log_output(
            "{} evaluation {} output for attempt {} on {} in {}:\n{}",
            self.get_analysis_name(),
            phase,
            attempt_index,
            evaluation_input.resolution_key,
            evaluation_input.restored_playground_name,
            command_result.output_tail,
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

    def expected_java_home(self, evaluation_input: EvaluationInput, redis=None) -> tuple[str | None, str | None]:
        try:
            repo_name, merge_sha = parse_schesch_playground_name(evaluation_input.restored_playground_name)
        except RuntimeError as error:
            return None, str(error)

        redis = redis or setup_redis_connection()
        key = schesch_info_key(repo_name, merge_sha)
        payload = redis.json().get(key)
        if not payload:
            return None, f"No Schesch info record found at {key}"

        java_home, error = determine_expected_java_home(payload)
        if error is not None or java_home is None:
            return None, f"Could not determine expected Java home from {key}: {error}"

        logger.info(
            "{} evaluation will reuse Java home {} from {}",
            self.get_analysis_name(),
            java_home,
            key,
        )
        return java_home, None

    def playground_path(self, evaluation_input: EvaluationInput) -> tuple[Path | None, str | None]:
        playgrounds = os.environ.get("PLAYGROUNDS")
        if playgrounds is None:
            return None, "PLAYGROUNDS environment variable is not set"
        return Path(playgrounds) / evaluation_input.restored_playground_name, None
