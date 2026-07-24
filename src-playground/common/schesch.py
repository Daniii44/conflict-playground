import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath

from common.evaluation_models import (
    ScheschCommandResult,
    ScheschJavaAttempt,
    ScheschResolutionResult,
)
from common.git_util import capture_git


DEFAULT_TIMEOUT_SECONDS = 15 * 60
OUTPUT_TAIL_CHARS = 12000
JAVA_HOME_ENV_VARS = ("JAVA8_HOME", "JAVA11_HOME", "JAVA17_HOME")
RESTORED_PLAYGROUND_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S.%fZ"


class BuildCommands:
    def __init__(self, build_tool: str, compile_command: list[str], test_command: list[str]):
        self.build_tool = build_tool
        self.compile_command = compile_command
        self.test_command = test_command


def normalize_test_selector(selector: str) -> str:
    stripped = selector.strip()
    if not stripped:
        raise RuntimeError("Test selector must not be empty")

    basename = Path(stripped.replace("\\", "/")).name
    if basename.endswith(".java"):
        return basename.removesuffix(".java")
    return basename


def filtered_test_command(build_commands: BuildCommands, test_selectors: list[str]) -> list[str]:
    normalized = [normalize_test_selector(selector) for selector in test_selectors]
    if build_commands.build_tool == "gradle":
        command = list(build_commands.test_command)
        for selector in normalized:
            command.extend(["--tests", selector])
        return command
    if build_commands.build_tool == "maven":
        return [*build_commands.test_command, f"-Dtest={','.join(normalized)}"]
    raise RuntimeError(f"Unsupported build tool for filtered tests: {build_commands.build_tool}")


def is_java_test_path(path: str) -> bool:
    posix_path = PurePosixPath(path)
    return path.endswith(".java") and any("test" in part.lower() for part in posix_path.parts)


def test_selectors_from_patch(patch: str) -> list[str]:
    selectors: list[str] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("+++ "):
            continue
        path = line.removeprefix("+++ ").strip()
        if path == "/dev/null" or not path.startswith("b/"):
            continue
        file_path = path.removeprefix("b/")
        if not is_java_test_path(file_path):
            continue
        selector = normalize_test_selector(file_path)
        if selector not in seen:
            selectors.append(selector)
            seen.add(selector)
    return selectors


def test_selectors_from_patch_bytes(patch: bytes) -> list[str]:
    selectors: list[str] = []
    seen: set[str] = set()
    for raw_line in patch.splitlines():
        if not raw_line.startswith(b"+++ "):
            continue
        line = raw_line.decode("utf-8", errors="surrogateescape")
        path = line.removeprefix("+++ ").strip()
        if path == "/dev/null" or not path.startswith("b/"):
            continue
        file_path = path.removeprefix("b/")
        if not is_java_test_path(file_path):
            continue
        selector = normalize_test_selector(file_path)
        if selector not in seen:
            selectors.append(selector)
            seen.add(selector)
    return selectors


test_selectors_from_patch.__test__ = False
test_selectors_from_patch_bytes.__test__ = False


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


def parse_schesch_playground_name(playground_name: str) -> tuple[str, str]:
    git_marker = ".git-"
    marker_index = playground_name.find(git_marker)
    if marker_index == -1:
        raise RuntimeError(f"Could not extract merge SHA from playground name: {playground_name}")

    repo_name = playground_name[: marker_index + len(".git")]
    remainder = playground_name[marker_index + len(git_marker):]
    if not remainder:
        raise RuntimeError(f"Could not extract merge SHA from playground name: {playground_name}")

    merge_sha = remainder
    if "-" in remainder:
        maybe_timestamp, maybe_merge_sha = remainder.split("-", 1)
        try:
            datetime.strptime(maybe_timestamp, RESTORED_PLAYGROUND_TIMESTAMP_FORMAT)
        except ValueError:
            pass
        else:
            if not maybe_merge_sha:
                raise RuntimeError(f"Could not extract merge SHA from playground name: {playground_name}")
            merge_sha = maybe_merge_sha

    return repo_name, merge_sha


def schesch_info_key(repo_name: str, merge_sha: str) -> str:
    return f"info:conflict:schesch:{repo_name}:{merge_sha}"


def determine_expected_java_home(schesch_info: dict) -> tuple[str | None, str | None]:
    human = schesch_info.get("human")
    parents = schesch_info.get("parents") or []
    results = [human, *parents]
    if human is None or len(parents) != 2:
        return None, "Schesch info record does not contain one human result and two parent results"

    if not all(result and result.get("passed") for result in results):
        return None, "Schesch info record does not show all tested resolutions passing"

    java_homes = {result.get("successful_java_home") for result in results}
    if None in java_homes or len(java_homes) != 1:
        return None, "Schesch info record does not resolve to one successful Java home"

    return next(iter(java_homes)), None


def java_home_env_var(java_home: str) -> str | None:
    expected = Path(java_home).resolve(strict=False)
    for env_var in JAVA_HOME_ENV_VARS:
        value = os.environ.get(env_var)
        if not value:
            continue
        if Path(value).resolve(strict=False) == expected:
            return env_var
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

    def run_tests_in_current_state(
        self,
        playground_path: Path,
        label: str,
        commit_sha: str | None = None,
        java_homes: list[str] | None = None,
        test_command: list[str] | None = None,
    ) -> ScheschResolutionResult:
        record = ScheschResolutionResult(label=label, commit_sha=commit_sha)
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
        selected_test_command = test_command or build_commands.test_command

        selected_java_homes = java_homes
        if selected_java_homes is None:
            selected_java_homes, java_error = self.java_homes()
            if java_error is not None:
                record.error = java_error
                return record

        deadline = time.monotonic() + self.timeout_seconds
        saw_successful_compilation = False
        saw_test_failure = False

        for java_home in selected_java_homes:
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
                selected_test_command,
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

    def run_tests_for_ref(
        self,
        playground_path: Path,
        ref: str,
        label: str,
        commit_sha: str | None = None,
        java_homes: list[str] | None = None,
        test_command: list[str] | None = None,
    ) -> ScheschResolutionResult:
        checkout_error = reset_playground(playground_path, ref)
        if checkout_error is not None:
            record = ScheschResolutionResult(label=label, commit_sha=commit_sha)
            record.error = f"Could not checkout {label} resolution: {checkout_error}"
            return record
        return self.run_tests_in_current_state(
            playground_path,
            label,
            commit_sha,
            java_homes=java_homes,
            test_command=test_command,
        )
