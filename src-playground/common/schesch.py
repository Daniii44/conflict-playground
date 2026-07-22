import os
import subprocess
import time
from pathlib import Path

from common.evaluation_models import (
    ScheschCommandResult,
    ScheschJavaAttempt,
    ScheschResolutionResult,
)
from common.git_util import capture_git


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


def read_head_commit(playground_path: str) -> tuple[str | None, str | None]:
    head_result = capture_git("-C", playground_path, "rev-parse", "HEAD", check=False)
    if head_result.returncode == 0:
        return head_result.stdout.strip(), None

    error = head_result.stderr.strip() or head_result.stdout.strip()
    return None, f"Could not read resolved HEAD: {error}"


def reset_playground(playground_path: Path, ref: str) -> str | None:
    for command in (
        ("reset", "--hard"),
        ("clean", "-fdx"),
        ("checkout", "--detach", "--force", ref),
        ("reset", "--hard", ref),
        ("clean", "-fdx"),
    ):
        result = capture_git("-C", str(playground_path), *command, check=False)
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip()
    return None


class ScheschResolutionRunner:
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, stream_output: bool = False):
        self.timeout_seconds = timeout_seconds
        self.stream_output = stream_output

    def detect_build_commands(self, playground_path: Path) -> BuildCommands | str:
        gradlew = playground_path / "gradlew"
        pom = playground_path / "pom.xml"
        mvnw = playground_path / "mvnw"

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
        playground_path: Path,
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
            run_kwargs = {
                "cwd": playground_path,
                "env": env,
                "text": True,
                "timeout": remaining_seconds,
                "check": False,
            }
            if not self.stream_output:
                run_kwargs["capture_output"] = True

            result = subprocess.run(command, **run_kwargs)
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
            output_tail=output_tail(f"{command_output_text(result.stdout)}{command_output_text(result.stderr)}"),
        )

    def run_tests_for_ref(
        self,
        playground_path: Path,
        ref: str,
        label: str,
        commit_sha: str | None = None,
    ) -> ScheschResolutionResult:
        checkout_error = reset_playground(playground_path, ref)
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
