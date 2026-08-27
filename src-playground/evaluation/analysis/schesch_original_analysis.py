from loguru import logger

from common.evaluation_models import EvaluationInput, MergeScheschEvaluation
from common.redis_util import setup_redis_connection
from common.schesch import DEFAULT_TIMEOUT_SECONDS, reset_playground
from evaluation.analysis.common import actual_resolution_sha_from_playground_name, read_head_commit
from evaluation.analysis.schesch_analysis import (
    SCHESCH_TEST_EXECUTION_RETRIES,
    BaseScheschEvaluationAnalysis,
)


class ScheschOriginalEvaluationAnalysis(BaseScheschEvaluationAnalysis):
    def __init__(self, analysis_name: str = "schesch-original", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        super().__init__(analysis_name, timeout_seconds)

    def analyse(self, evaluation_input: EvaluationInput) -> MergeScheschEvaluation:
        self.log_analysis_start(evaluation_input)
        proposed_resolution = evaluation_input.resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")

        if proposed_resolution.git_archive is None:
            error = proposed_resolution.error or "Resolution has no archived .git repository"
            return self.failed(evaluation_input, error)

        playground_path, path_error = self.playground_path(evaluation_input)
        if path_error is not None or playground_path is None:
            return self.failed(evaluation_input, path_error or "Could not resolve playground path")
        logger.info(
            "{} evaluation will use restored playground path {}",
            self.get_analysis_name(),
            playground_path,
        )

        proposed_commit_sha, head_error = read_head_commit(str(playground_path))
        actual_resolution_sha = actual_resolution_sha_from_playground_name(evaluation_input.restored_playground_name)
        if actual_resolution_sha is None:
            return self.failed(
                evaluation_input,
                f"Could not extract merge SHA from playground name: {evaluation_input.restored_playground_name}",
            )
        logger.info(
            "{} evaluation resolved proposed HEAD {} and actual resolution {}",
            self.get_analysis_name(),
            proposed_commit_sha,
            actual_resolution_sha,
        )

        redis = setup_redis_connection()
        expected_java_home, expected_java_home_error = self.expected_java_home(evaluation_input, redis)
        if expected_java_home_error is not None or expected_java_home is None:
            return self.failed(
                evaluation_input,
                expected_java_home_error or "Could not determine expected Java home",
            )

        proposed = None
        if head_error is None:
            logger.info(
                "{} evaluation is running Schesch tests for proposed HEAD {} with {}",
                self.get_analysis_name(),
                proposed_commit_sha,
                expected_java_home,
            )
            proposed = self.run_tests_for_ref(
                playground_path,
                "HEAD",
                "proposed",
                proposed_commit_sha,
                java_homes=[expected_java_home],
                test_execution_retries=SCHESCH_TEST_EXECUTION_RETRIES,
            )
            self.log_resolution_result(evaluation_input, proposed)
        else:
            logger.warning(
                "{} evaluation could not read proposed HEAD in {}: {}",
                self.get_analysis_name(),
                playground_path,
                head_error,
            )

        restore_error = None
        if proposed_commit_sha is not None:
            logger.info(
                "{} evaluation is resetting restored playground {} back to {}",
                self.get_analysis_name(),
                playground_path,
                proposed_commit_sha,
            )
            restore_error = reset_playground(playground_path, proposed_commit_sha)
            if restore_error is None:
                logger.info(
                    "{} evaluation reset restored playground {} back to {}",
                    self.get_analysis_name(),
                    playground_path,
                    proposed_commit_sha,
                )
            else:
                logger.warning(
                    "{} evaluation could not reset restored playground {} back to {}: {}",
                    self.get_analysis_name(),
                    playground_path,
                    proposed_commit_sha,
                    restore_error,
                )

        error = head_error
        if restore_error is not None:
            error = f"{error}; {restore_error}" if error else restore_error

        return MergeScheschEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            timeout_seconds=self.timeout_seconds,
            test_execution_retries=SCHESCH_TEST_EXECUTION_RETRIES,
            proposed=proposed,
            error=error,
        )

    def rerun_existing_test_failure(
        self,
        evaluation_input: EvaluationInput,
        existing: MergeScheschEvaluation,
        redis=None,
    ) -> MergeScheschEvaluation:
        playground_path, path_error = self.playground_path(evaluation_input)
        if path_error is not None or playground_path is None:
            existing.error = path_error or "Could not resolve playground path"
            return existing

        proposed = existing.proposed
        proposed_commit_sha = existing.proposed_commit_sha
        if proposed is None or proposed_commit_sha is None:
            existing.error = "Existing Schesch evaluation has no proposed resolution commit"
            return existing

        checkout_error = reset_playground(playground_path, proposed_commit_sha)
        if checkout_error is not None:
            existing.error = f"Could not checkout proposed resolution for retry: {checkout_error}"
            return existing

        try:
            existing.proposed = self.rerun_failed_tests_in_current_state(
                playground_path,
                proposed,
                retries=SCHESCH_TEST_EXECUTION_RETRIES,
            )
            if existing.proposed.passed:
                existing.error = None
        finally:
            restore_error = reset_playground(playground_path, proposed_commit_sha)
            if restore_error is not None:
                existing.error = f"Could not reset proposed resolution after retry: {restore_error}"

        return existing
