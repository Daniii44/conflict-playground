from loguru import logger

from common.evaluation_models import EvaluationInput, MergeScheschEvaluation
from common.redis_util import setup_redis_connection
from common.schesch import (
    DEFAULT_TIMEOUT_SECONDS,
    filtered_test_command,
    parse_schesch_playground_name,
    reset_playground,
    test_selectors_from_patch_bytes,
)
from dataset.schesch.tests.apply import apply_patch_to_current_head, load_generated_tests
from dataset.schesch.tests.generate import generated_patch_bytes, generated_tests_record_key
from evaluation.analysis.common import actual_resolution_sha_from_playground_name, read_head_commit
from evaluation.analysis.schesch_analysis import (
    SCHESCH_TEST_EXECUTION_RETRIES,
    BaseScheschEvaluationAnalysis,
)


class ScheschGeneratedEvaluationAnalysis(BaseScheschEvaluationAnalysis):
    def __init__(self, analysis_name: str = "schesch-generated", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        super().__init__(analysis_name, timeout_seconds)

    def generated_tests_key(self, evaluation_input: EvaluationInput) -> tuple[str | None, str | None]:
        try:
            repo_name, merge_sha = parse_schesch_playground_name(evaluation_input.restored_playground_name)
        except RuntimeError as error:
            return None, str(error)
        return generated_tests_record_key(repo_name, merge_sha), None

    def generated_test_command(self, playground_path, patch: bytes) -> tuple[list[str] | None, str | None]:
        selectors = test_selectors_from_patch_bytes(patch)
        if not selectors:
            logger.warning(
                "{} evaluation found no Java test selectors in generated test patch for {}",
                self.get_analysis_name(),
                playground_path,
            )
            return None, "Generated Schesch test patch does not modify any Java test classes"
        logger.info(
            "{} evaluation derived {} generated Schesch test selector(s) for {}: {}",
            self.get_analysis_name(),
            len(selectors),
            playground_path,
            ", ".join(selectors),
        )

        build_commands = self.detect_build_commands(playground_path)
        if isinstance(build_commands, str):
            logger.warning(
                "{} evaluation could not determine build commands for {}: {}",
                self.get_analysis_name(),
                playground_path,
                build_commands,
            )
            return None, build_commands
        command = filtered_test_command(build_commands, selectors)
        logger.info(
            "{} evaluation will run generated Schesch tests with {} command {}",
            self.get_analysis_name(),
            build_commands.build_tool,
            command,
        )
        return command, None

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

        generated_key, generated_key_error = self.generated_tests_key(evaluation_input)
        if generated_key_error is not None or generated_key is None:
            return self.failed(evaluation_input, generated_key_error or "Could not derive generated test key")
        logger.info(
            "{} evaluation will load generated Schesch tests from {}",
            self.get_analysis_name(),
            generated_key,
        )

        generated_tests = None
        generated_tests_error = None
        if head_error is None:
            try:
                generated_tests = load_generated_tests(redis, generated_key)
                patch_bytes = generated_patch_bytes(generated_tests) or b""
                logger.info(
                    "{} evaluation loaded generated Schesch patch from {} ({} bytes)",
                    self.get_analysis_name(),
                    generated_key,
                    len(patch_bytes),
                )
            except RuntimeError as error:
                generated_tests_error = str(error)
                logger.warning(
                    "{} evaluation could not load generated Schesch tests from {}: {}",
                    self.get_analysis_name(),
                    generated_key,
                    generated_tests_error,
                )
        else:
            logger.warning(
                "{} evaluation could not read proposed HEAD in {}: {}",
                self.get_analysis_name(),
                playground_path,
                head_error,
            )

        proposed = None
        apply_error = None
        restore_error = None

        try:
            if head_error is None and generated_tests_error is None and generated_tests is not None:
                patch_bytes = generated_patch_bytes(generated_tests) or b""
                test_command, test_command_error = self.generated_test_command(playground_path, patch_bytes)
                if test_command_error is not None:
                    apply_error = test_command_error
                    logger.warning(
                        "{} evaluation could not prepare generated Schesch tests for {}: {}",
                        self.get_analysis_name(),
                        playground_path,
                        apply_error,
                    )
                else:
                    logger.info(
                        "{} evaluation is applying generated Schesch test patch from {} to {}",
                        self.get_analysis_name(),
                        generated_key,
                        playground_path,
                    )
                    applied_commit_sha = apply_patch_to_current_head(playground_path, patch_bytes)
                    logger.info(
                        "{} evaluation applied generated Schesch test patch and produced commit {}",
                        self.get_analysis_name(),
                        applied_commit_sha,
                    )
                    proposed = self.run_tests_in_current_state(
                        playground_path,
                        "proposed",
                        commit_sha=applied_commit_sha,
                        java_homes=[expected_java_home],
                        test_command=test_command,
                        test_execution_retries=SCHESCH_TEST_EXECUTION_RETRIES,
                    )
                    self.log_resolution_result(evaluation_input, proposed)
        except RuntimeError as error:
            apply_error = str(error)
            logger.warning(
                "{} evaluation failed while applying or running generated Schesch tests in {}: {}",
                self.get_analysis_name(),
                playground_path,
                apply_error,
            )
        finally:
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

        error = head_error or generated_tests_error or apply_error
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
            existing.error = "Existing generated Schesch evaluation has no proposed resolution commit"
            return existing

        generated_key, generated_key_error = self.generated_tests_key(evaluation_input)
        if generated_key_error is not None or generated_key is None:
            existing.error = generated_key_error or "Could not derive generated test key"
            return existing

        if redis is None:
            redis = setup_redis_connection()
        try:
            generated_tests = load_generated_tests(redis, generated_key)
            patch_bytes = generated_patch_bytes(generated_tests) or b""
            reset_error = reset_playground(playground_path, proposed_commit_sha)
            if reset_error is not None:
                existing.error = f"Could not checkout proposed resolution for retry: {reset_error}"
                return existing
            apply_patch_to_current_head(playground_path, patch_bytes)
            existing.proposed = self.rerun_failed_tests_in_current_state(
                playground_path,
                proposed,
                retries=SCHESCH_TEST_EXECUTION_RETRIES,
            )
            if existing.proposed.passed:
                existing.error = None
        except RuntimeError as error:
            existing.error = str(error)
        finally:
            restore_error = reset_playground(playground_path, proposed_commit_sha)
            if restore_error is not None:
                existing.error = f"Could not reset proposed resolution after retry: {restore_error}"

        return existing
