from common.evaluation_models import EvaluationInput, MergeScheschEvaluation
from common.redis_util import setup_redis_connection
from common.schesch import (
    DEFAULT_TIMEOUT_SECONDS,
    filtered_test_command,
    parse_schesch_playground_name,
    reset_playground,
    test_selectors_from_patch,
)
from dataset.schesch.tests.apply import apply_patch_to_current_head, load_generated_tests
from dataset.schesch.tests.generate import generated_tests_record_key
from evaluation.analysis.common import actual_resolution_sha_from_playground_name, read_head_commit
from evaluation.analysis.schesch_analysis import BaseScheschEvaluationAnalysis


class ScheschGeneratedEvaluationAnalysis(BaseScheschEvaluationAnalysis):
    def __init__(self, analysis_name: str = "schesch-generated", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        super().__init__(analysis_name, timeout_seconds)

    def generated_tests_key(self, evaluation_input: EvaluationInput) -> tuple[str | None, str | None]:
        try:
            repo_name, merge_sha = parse_schesch_playground_name(evaluation_input.restored_playground_name)
        except RuntimeError as error:
            return None, str(error)
        return generated_tests_record_key(repo_name, merge_sha), None

    def generated_test_command(self, playground_path, patch: str) -> tuple[list[str] | None, str | None]:
        selectors = test_selectors_from_patch(patch)
        if not selectors:
            return None, "Generated Schesch test patch does not modify any Java test classes"

        build_commands = self.detect_build_commands(playground_path)
        if isinstance(build_commands, str):
            return None, build_commands
        return filtered_test_command(build_commands, selectors), None

    def analyse(self, evaluation_input: EvaluationInput) -> MergeScheschEvaluation:
        proposed_resolution = evaluation_input.resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")

        if proposed_resolution.git_archive is None:
            error = proposed_resolution.error or "Resolution has no archived .git repository"
            return self.failed(evaluation_input, error)

        playground_path, path_error = self.playground_path(evaluation_input)
        if path_error is not None or playground_path is None:
            return self.failed(evaluation_input, path_error or "Could not resolve playground path")

        proposed_commit_sha, head_error = read_head_commit(str(playground_path))
        actual_resolution_sha = actual_resolution_sha_from_playground_name(evaluation_input.restored_playground_name)
        if actual_resolution_sha is None:
            return self.failed(
                evaluation_input,
                f"Could not extract merge SHA from playground name: {evaluation_input.restored_playground_name}",
            )

        generated_key, generated_key_error = self.generated_tests_key(evaluation_input)
        if generated_key_error is not None or generated_key is None:
            return self.failed(evaluation_input, generated_key_error or "Could not derive generated test key")

        generated_tests = None
        generated_tests_error = None
        if head_error is None:
            try:
                generated_tests = load_generated_tests(setup_redis_connection(), generated_key)
            except RuntimeError as error:
                generated_tests_error = str(error)

        proposed = None
        apply_error = None
        restore_error = None

        try:
            if head_error is None and generated_tests_error is None and generated_tests is not None:
                test_command, test_command_error = self.generated_test_command(playground_path, generated_tests.patch or "")
                if test_command_error is not None:
                    apply_error = test_command_error
                else:
                    applied_commit_sha = apply_patch_to_current_head(playground_path, generated_tests.patch or "")
                    proposed = self.run_tests_in_current_state(
                        playground_path,
                        "proposed",
                        commit_sha=applied_commit_sha,
                        test_command=test_command,
                    )
        except RuntimeError as error:
            apply_error = str(error)
        finally:
            if proposed_commit_sha is not None:
                restore_error = reset_playground(playground_path, proposed_commit_sha)

        error = head_error or generated_tests_error or apply_error
        if restore_error is not None:
            error = f"{error}; {restore_error}" if error else restore_error

        return MergeScheschEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            timeout_seconds=self.timeout_seconds,
            proposed=proposed,
            error=error,
        )
