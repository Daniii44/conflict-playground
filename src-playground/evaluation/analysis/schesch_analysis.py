import os
import subprocess
import time
from pathlib import Path

from common.evaluation_models import (
    EvaluationInput,
    MergeScheschEvaluation,
    ScheschCommandResult,
    ScheschJavaAttempt,
    ScheschResolutionResult,
)
from common.git_util import capture_git
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)


DEFAULT_TIMEOUT_SECONDS = 15 * 60
OUTPUT_TAIL_CHARS = 12000
JAVA_HOME_ENV_VARS = ("JAVA8_HOME", "JAVA11_HOME", "JAVA17_HOME")


class BuildCommands:
    def __init__(self, build_tool: str, compile_command: list[str], test_command: list[str]):
        self.build_tool = build_tool
        self.compile_command = compile_command
        self.test_command = test_command


def output_tail(output: str, limit: int = OUTPUT_TAIL_CHARS) -> str:
    if len(output) <= limit:
        return output
    return output[-limit:]


def command_output_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output


class ScheschEvaluationAnalysis(EvaluationAnalysis):
    def __init__(self, analysis_name: str = "schesch", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        super().__init__(analysis_name)
        self.timeout_seconds = timeout_seconds

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

    def detect_build_commands(self, repo_path: Path) -> BuildCommands | str:
        gradlew = repo_path / "gradlew"
        pom = repo_path / "pom.xml"
        mvnw = repo_path / "mvnw"

        if gradlew.is_file():
            return BuildCommands("gradle", ["./gradlew", "clean", "testClasses"], ["./gradlew", "clean", "test"])
        if pom.is_file():
            mvn_command = "./mvnw" if mvnw.is_file() else "mvn"
            return BuildCommands("maven", [mvn_command, "clean", "test-compile"], [mvn_command, "clean", "test"])
        return "No Gradle or Maven buildfile"

    def java_homes(self) -> tuple[list[str], str | None]:
        homes = []
        for env_var in JAVA_HOME_ENV_VARS:
            java_home = os.environ.get(env_var)
            if not java_home:
                return [], f"{env_var} is not set"
            if not Path(java_home).is_dir():
                return [], f"{env_var} is set to a nonexistent directory: {java_home}"
            homes.append(java_home)
        return homes, None

    def run_command(
        self,
        repo_path: Path,
        command: list[str],
        java_home: str,
        deadline: float,
    ) -> ScheschCommandResult:
        remaining_seconds = max(0.0, deadline - time.monotonic())
        if remaining_seconds <= 0:
            return ScheschCommandResult(
                command=command,
                duration_seconds=0.0,
                timed_out=True,
                output_tail="Timed out before command start",
            )

        env = os.environ.copy()
        env["JAVA_HOME"] = java_home
        env["PATH"] = f"{java_home}/bin:{env.get('PATH', '')}"

        start = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=repo_path,
                env=env,
                text=True,
                capture_output=True,
                timeout=remaining_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            duration_seconds = time.monotonic() - start
            stdout = command_output_text(error.stdout)
            stderr = command_output_text(error.stderr)
            return ScheschCommandResult(
                command=command,
                duration_seconds=duration_seconds,
                timed_out=True,
                output_tail=output_tail(f"{stdout}{stderr}"),
            )

        duration_seconds = time.monotonic() - start
        return ScheschCommandResult(
            command=command,
            returncode=result.returncode,
            duration_seconds=duration_seconds,
            output_tail=output_tail(f"{result.stdout}{result.stderr}"),
        )

    def prepare_worktree(self, playground_path: Path, ref: str) -> str | None:
        for command in (
            ("reset", "--hard"),
            ("clean", "-fdx"),
            ("checkout", "--force", ref),
            ("reset", "--hard"),
            ("clean", "-fdx"),
        ):
            result = capture_git("-C", str(playground_path), *command, check=False)
            if result.returncode != 0:
                return result.stderr.strip() or result.stdout.strip()
        return None

    def run_tests_for_ref(
        self,
        playground_path: Path,
        ref: str,
        label: str,
        commit_sha: str | None = None,
    ) -> ScheschResolutionResult:
        checkout_error = self.prepare_worktree(playground_path, ref)
        record = ScheschResolutionResult(label=label, commit_sha=commit_sha)
        if checkout_error is not None:
            record.error = f"Could not checkout {label} resolution: {checkout_error}"
            return record

        head_sha, head_error = read_head_commit(str(playground_path))
        record.commit_sha = commit_sha or head_sha
        if head_error is not None:
            record.error = head_error
            return record

        build_commands = self.detect_build_commands(playground_path)
        if isinstance(build_commands, str):
            record.error = build_commands
            record.compilation_failed = True
            return record
        record.build_tool = build_commands.build_tool

        java_homes, java_error = self.java_homes()
        if java_error is not None:
            record.error = java_error
            return record

        deadline = time.monotonic() + self.timeout_seconds
        saw_successful_compilation = False
        saw_test_failure = False

        for java_home in java_homes:
            attempt = ScheschJavaAttempt(java_home=java_home)
            record.attempts.append(attempt)

            attempt.compile_result = self.run_command(
                playground_path,
                build_commands.compile_command,
                java_home,
                deadline,
            )
            if attempt.compile_result.timed_out:
                record.timed_out = True
                break
            if attempt.compile_result.returncode != 0:
                continue

            saw_successful_compilation = True
            attempt.test_result = self.run_command(
                playground_path,
                build_commands.test_command,
                java_home,
                deadline,
            )
            if attempt.test_result.timed_out:
                record.timed_out = True
                break
            if attempt.test_result.returncode == 0:
                record.passed = True
                record.successful_java_home = java_home
                return record
            saw_test_failure = True

        record.compilation_failed = not saw_successful_compilation and not record.timed_out
        record.test_execution_failed = saw_successful_compilation and saw_test_failure and not record.timed_out
        if record.timed_out:
            record.error = f"Timed out after {self.timeout_seconds} seconds"
        return record

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

        proposed = None
        if head_error is None:
            proposed = self.run_tests_for_ref(
                playground_path,
                "HEAD",
                "proposed",
                proposed_commit_sha,
            )

        human = self.run_tests_for_ref(playground_path, actual_resolution_sha, "human", actual_resolution_sha)
        restore_error = None
        if proposed_commit_sha is not None:
            restore_error = self.prepare_worktree(playground_path, proposed_commit_sha)

        error = head_error
        if restore_error is not None:
            error = f"{error}; {restore_error}" if error else restore_error

        return MergeScheschEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            timeout_seconds=self.timeout_seconds,
            proposed=proposed,
            human=human,
            error=error,
        )
