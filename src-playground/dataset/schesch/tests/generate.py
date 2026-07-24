#!/usr/bin/env python3

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from common.git_util import capture_git, capture_git_bytes, git_env
from common.merge_tree import ConflictType
from common.redis_util import setup_redis_connection
from common.schesch import (
    ScheschResolutionRunner,
    determine_expected_java_home,
    filtered_test_command,
    reset_playground,
    schesch_info_key,
    test_selectors_from_patch_bytes,
)
from dataset.schesch.merge_lookup import resolve_unique_merge_sha_from_parents
from info.conflict.analysis.core_analysis import InfoConflictCore
from playground.setup import setup_playground


TEST_GENERATION_PREFIX = "dataset:schesch:tests:"
DEFAULT_OPENCODE_EXECUTABLE = "/root/.opencode/bin/opencode"
DEFAULT_OPENCODE_TIMEOUT_SECONDS = 20 * 60
OUTPUT_TAIL_CHARS = 12000


class GeneratedTestFile(BaseModel):
    path: str
    prompt: str
    duration_seconds: float
    opencode_exit_code: int | None = None
    opencode_session_export: dict[str, Any] | None = None
    output_tail: str | None = None
    error: str | None = None


class ScheschGeneratedTests(BaseModel):
    repo: str
    merge_sha: str
    redis_key: str
    conflict_info_key: str
    playground_name: str | None = None
    human_solution_ref: str
    generated_at: datetime
    duration_seconds: float
    files: list[GeneratedTestFile] = Field(default_factory=list)
    human: dict[str, Any] | None = None
    patch: str | None = None
    patch_base64: str | None = None
    test_commit_sha: str | None = None
    coverage: dict[str, Any] | None = None
    error: str | None = None


def generated_tests_record_key(repo_name: str, merge_sha: str) -> str:
    return f"{TEST_GENERATION_PREFIX}{repo_name}:{merge_sha}"


def conflict_info_key(repo_name: str, merge_sha: str) -> str:
    return f"info:conflict:core:{repo_name}:{merge_sha}"


def output_tail(stdout: str | None, stderr: str | None, limit: int = OUTPUT_TAIL_CHARS) -> str | None:
    output = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    if not output:
        return None
    if len(output) <= limit:
        return output
    return output[-limit:]


def content_conflict_paths(conflict_info: InfoConflictCore) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for conflict in conflict_info.merge_result.logical_conflicts:
        if conflict.type != ConflictType.CONFLICT_CONTENTS:
            continue
        for path in conflict.paths:
            if path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def prompt_for_file(conflict_info: InfoConflictCore, file_path: str) -> str:
    file_conflicts = [
        conflict.model_dump(mode="json")
        for conflict in conflict_info.merge_result.logical_conflicts
        if file_path in conflict.paths
    ]
    conflict_json = json.dumps(file_conflicts, indent=2, sort_keys=True)
    return (
        "Generate unit tests that capture the intent of the human merge conflict resolution "
        f"for `{file_path}`.\n\n"
        "Context:\n"
        f"- Repository: {conflict_info.repo}\n"
        f"- Merge commit containing the human sample solution: {conflict_info.merge_commit_oid}\n"
        f"- Conflicting file to focus on: {file_path}\n"
        "- The playground is reset to the human sample solution. Treat the current contents "
        "of the target file as the reference behavior.\n"
        "- Only generate or update tests needed to exercise that resolved behavior. Do not edit "
        "production source files unless a test framework requires a minimal fixture/configuration change.\n"
        "- The generated patch is only useful if `playground-schesch-test` passes. If the targeted "
        "Schesch test command fails, revise the generated tests until it passes or stop and report the failure.\n"
        "- Validate only with `playground-schesch-test`. After generating tests, run "
        "`playground-schesch-test -t <GeneratedTestClass.java>` for each generated or updated test class. "
        "If you create multiple test classes, pass multiple `-t` flags. Do not run a broader test suite, "
        "and do not consider the task complete until that command succeeds.\n"
        "- Keep the change scoped to this file's resolved behavior; do not generate tests for other "
        "conflicting files in this run.\n\n"
        "Conflict metadata for this file:\n"
        f"{conflict_json}\n"
    )


def run_opencode_for_file(
    playground_path: Path,
    opencode_executable: str,
    prompt: str,
    timeout_seconds: int,
) -> tuple[int | None, str | None, str | None, float]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                opencode_executable,
                "run",
                "--dir",
                str(playground_path),
                prompt,
            ],
            cwd=playground_path,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=git_env(),
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - start
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        return None, output_tail(stdout, stderr), f"opencode timed out after {timeout_seconds} seconds", duration
    except FileNotFoundError:
        duration = time.monotonic() - start
        return None, None, f"opencode executable not found: {opencode_executable}", duration

    duration = time.monotonic() - start
    error = None
    if result.returncode != 0:
        error = f"opencode exited with code {result.returncode}"
    return result.returncode, output_tail(result.stdout, result.stderr), error, duration


def run_opencode_json(
    playground_path: Path,
    opencode_executable: str,
    *args: str,
) -> tuple[Any | None, str | None]:
    logger.info(
        "Running opencode JSON command in {}: {} {}",
        playground_path,
        opencode_executable,
        " ".join(args),
    )
    with tempfile.NamedTemporaryFile(mode="w+") as tf:
        result = subprocess.run(
            [opencode_executable, *args],
            cwd=playground_path,
            text=True,
            stdout=tf,
            stderr=subprocess.PIPE,
            check=False,
            env=git_env(),
        )
        tf.seek(0)
        json_text = tf.read()
    logger.info(
        "Finished opencode JSON command {} rc={} stdout_chars={} stderr_chars={}",
        " ".join(args),
        result.returncode,
        len(json_text),
        len(result.stderr or ""),
    )
    if result.returncode != 0:
        error = (result.stderr or "").strip() or json_text.strip()
        return None, error or f"opencode {' '.join(args)} exited with code {result.returncode}"

    try:
        return json.loads(json_text), None
    except json.JSONDecodeError as error:
        return None, f"opencode {' '.join(args)} returned invalid JSON: {error}"


def latest_session_id(session_list: Any) -> str | None:
    if isinstance(session_list, list) and session_list:
        session = session_list[0]
    elif isinstance(session_list, dict):
        sessions = session_list.get("sessions")
        if isinstance(sessions, list) and sessions:
            session = sessions[0]
        else:
            session = session_list
    else:
        return None

    if not isinstance(session, dict):
        return None

    for key in ("id", "sessionID", "sessionId", "session_id"):
        value = session.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def export_latest_session(playground_path: Path, opencode_executable: str) -> dict[str, Any]:
    logger.info("Exporting latest opencode session for {}", playground_path)
    session_list, list_error = run_opencode_json(
        playground_path,
        opencode_executable,
        "session",
        "list",
        "--max-count",
        "1",
        "--format",
        "json",
    )
    if list_error is not None:
        return {"error": list_error}

    session_id = latest_session_id(session_list)
    if session_id is None:
        return {"error": "No latest opencode session ID found", "session_list": session_list}

    session_export, export_error = run_opencode_json(playground_path, opencode_executable, "export", session_id)
    if export_error is not None:
        return {"id": session_id, "error": export_error}
    return {"id": session_id, "data": session_export}


def has_worktree_changes(playground_path: Path) -> bool:
    result = capture_git("-C", str(playground_path), "status", "--porcelain")
    return bool(result.stdout.strip())


def commit_generated_tests(playground_path: Path) -> str | None:
    if not has_worktree_changes(playground_path):
        return None

    capture_git("-C", str(playground_path), "add", "-A")
    capture_git(
        "-C",
        str(playground_path),
        "-c",
        "user.name=Schesch Test Generator",
        "-c",
        "user.email=schesch-tests@example.invalid",
        "commit",
        "-m",
        "test(schesch): capture human conflict resolution intent",
    )
    return capture_git("-C", str(playground_path), "rev-parse", "HEAD").stdout.strip()


def encode_patch_base64(patch: bytes) -> str:
    return base64.b64encode(patch).decode("ascii")


def generated_patch_bytes(record: ScheschGeneratedTests) -> bytes | None:
    if record.patch_base64:
        try:
            return base64.b64decode(record.patch_base64)
        except ValueError:
            return None
    if record.patch and record.patch.strip():
        return record.patch.encode("utf-8")
    return None


def format_generated_patch(playground_path: Path, base_ref: str) -> bytes | None:
    result = capture_git_bytes(
        "-C",
        str(playground_path),
        "format-patch",
        "--stdout",
        f"{base_ref}..HEAD",
    )
    patch = result.stdout
    return patch if patch.strip() else None


def validate_generated_patch(patch: bytes) -> tuple[list[str], str | None]:
    selectors = test_selectors_from_patch_bytes(patch)
    if not selectors:
        return [], "opencode completed but did not modify any Java test classes"
    return selectors, None


def load_conflict_info(redis, repo_name: str, merge_sha: str) -> InfoConflictCore:
    key = conflict_info_key(repo_name, merge_sha)
    logger.info("Loading info:core conflict record from {}", key)
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No info:core conflict record found at {key}")
    conflict_info = InfoConflictCore.model_validate(payload)
    logger.info(
        "Loaded conflict record for {} {} with {} logical conflicts and {} conflicted file entries",
        conflict_info.repo,
        conflict_info.merge_commit_oid,
        len(conflict_info.merge_result.logical_conflicts),
        len(conflict_info.merge_result.conflicted_files),
    )
    return conflict_info


def expected_human_java_home(redis, repo_name: str, merge_sha: str) -> str:
    key = schesch_info_key(repo_name, merge_sha)
    logger.info("Loading Schesch conflict record from {}", key)
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No Schesch conflict record found at {key}")

    java_home, error = determine_expected_java_home(payload)
    if error is not None or java_home is None:
        raise RuntimeError(f"Could not determine expected Java home from {key}: {error}")
    return java_home


def human_resolution_error(result) -> str:
    if result.error:
        return result.error
    if result.compilation_failed:
        return "Human sample resolution does not compile under the expected Java home"
    if result.test_execution_failed:
        return "Human sample resolution fails Schesch tests under the expected Java home"
    if result.timed_out:
        return "Human sample resolution timed out under the expected Java home"
    return "Human sample resolution did not pass Schesch tests under the expected Java home"


def generated_test_command(playground_path: Path, selectors: list[str], timeout_seconds: int) -> tuple[list[str], str]:
    runner = ScheschResolutionRunner(timeout_seconds=timeout_seconds)
    build_commands = runner.detect_build_commands(playground_path)
    if isinstance(build_commands, str):
        raise RuntimeError(build_commands)
    return filtered_test_command(build_commands, selectors), build_commands.build_tool


def verify_human_solution(
    redis,
    playground_path: Path,
    repo_name: str,
    merge_sha: str,
    selectors: list[str],
    timeout_seconds: int,
):
    java_home = expected_human_java_home(redis, repo_name, merge_sha)
    test_command, build_tool = generated_test_command(playground_path, selectors, timeout_seconds)
    logger.info(
        "Running generated Schesch tests for human sample solution {} {} with {} using {} selectors",
        repo_name,
        merge_sha,
        java_home,
        len(selectors),
    )
    result = ScheschResolutionRunner(timeout_seconds=timeout_seconds).run_tests_in_current_state(
        playground_path,
        "human",
        commit_sha=merge_sha,
        java_homes=[java_home],
        test_command=test_command,
    )
    result.build_tool = result.build_tool or build_tool
    if not result.passed:
        raise RuntimeError(human_resolution_error(result))
    return result


def store_generation(redis, record: ScheschGeneratedTests) -> None:
    logger.info(
        "Storing Schesch generated test record at {} (files={}, patch={}, error={})",
        record.redis_key,
        len(record.files),
        generated_patch_bytes(record) is not None,
        record.error is not None,
    )
    redis.json().set(record.redis_key, "$", json.loads(record.model_dump_json()))


def generate_tests(
    redis,
    repo_name: str,
    merge_sha: str,
    *,
    opencode_executable: str = DEFAULT_OPENCODE_EXECUTABLE,
    timeout_seconds: int = DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    keep_playground: bool = False,
) -> ScheschGeneratedTests:
    started_at = time.monotonic()
    redis_key = generated_tests_record_key(repo_name, merge_sha)
    logger.info(
        "Starting Schesch test generation for {} {} using opencode {}",
        repo_name,
        merge_sha,
        opencode_executable,
    )
    record = ScheschGeneratedTests(
        repo=repo_name,
        merge_sha=merge_sha,
        redis_key=redis_key,
        conflict_info_key=conflict_info_key(repo_name, merge_sha),
        human_solution_ref=merge_sha,
        generated_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
    )

    playground_path: Path | None = None
    try:
        conflict_info = load_conflict_info(redis, repo_name, merge_sha)
        paths = content_conflict_paths(conflict_info)
        if not paths:
            raise RuntimeError(f"Conflict record {record.conflict_info_key} has no content conflict paths")
        logger.info("Selected {} content-conflicting files for test generation", len(paths))
        for index, path in enumerate(paths, start=1):
            logger.info("Content conflict file {}/{}: {}", index, len(paths), path)

        logger.info("Creating playground for {} {}", repo_name, merge_sha)
        playground_name = setup_playground(repo_name, merge_sha)
        record.playground_name = playground_name
        playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
        playground_path = playgrounds / playground_name
        logger.info("Created playground {} at {}", playground_name, playground_path)
        logger.info("Resetting playground to human sample solution {}", merge_sha)
        reset_error = reset_playground(playground_path, merge_sha)
        if reset_error is not None:
            raise RuntimeError(f"Could not reset playground to {merge_sha}: {reset_error}")
        logger.info("Prepared playground at human sample solution")

        for index, file_path in enumerate(paths, start=1):
            logger.info("Running opencode for file {}/{}: {}", index, len(paths), file_path)
            prompt = prompt_for_file(conflict_info, file_path)
            exit_code, tail, error, duration = run_opencode_for_file(
                playground_path,
                opencode_executable,
                prompt,
                timeout_seconds,
            )
            session_export = export_latest_session(playground_path, opencode_executable)
            record.files.append(
                GeneratedTestFile(
                    path=file_path,
                    prompt=prompt,
                    duration_seconds=duration,
                    opencode_exit_code=exit_code,
                    opencode_session_export=session_export,
                    output_tail=tail,
                    error=error,
                )
            )
            logger.info(
                "Finished opencode for {} in {:.2f}s with exit_code={} error={} session_export_keys={}",
                file_path,
                duration,
                exit_code,
                error is not None,
                sorted(session_export.keys()),
            )
            if error is not None:
                raise RuntimeError(f"Test generation failed for {file_path}: {error}")

        logger.info("Committing generated test changes")
        record.test_commit_sha = commit_generated_tests(playground_path)
        if record.test_commit_sha is None:
            logger.info("No generated test changes found to commit")
        else:
            logger.info("Committed generated tests as {}", record.test_commit_sha)
            logger.info("Formatting generated test patch against {}", merge_sha)
        patch_bytes = format_generated_patch(playground_path, merge_sha) if record.test_commit_sha else None
        if patch_bytes is None:
            record.error = "opencode completed but did not create any test changes"
            logger.info("No patch was produced for generated tests")
        else:
            record.patch_base64 = encode_patch_base64(patch_bytes)
            selectors, patch_error = validate_generated_patch(patch_bytes)
            if patch_error is not None:
                record.error = patch_error
                logger.warning("Generated test patch did not touch Java test classes")
            else:
                logger.info(
                    "Generated test patch modifies {} Java test selector(s): {}",
                    len(selectors),
                    ", ".join(selectors),
                )
                record.human = verify_human_solution(
                    redis,
                    playground_path,
                    repo_name,
                    merge_sha,
                    selectors,
                    timeout_seconds,
                ).model_dump(mode="json")
            logger.info("Generated test patch has {} bytes", len(patch_bytes))
    except Exception as error:
        record.error = str(error)
        logger.error("{}", error)
    finally:
        record.duration_seconds = time.monotonic() - started_at
        logger.info(
            "Finished Schesch test generation for {} {} in {:.2f}s",
            repo_name,
            merge_sha,
            record.duration_seconds,
        )
        store_generation(redis, record)
        if playground_path is not None and not keep_playground:
            logger.info("Removing playground {}", playground_path)
            shutil.rmtree(playground_path, ignore_errors=True)
        elif playground_path is not None:
            logger.info("Keeping playground {}", playground_path)

    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate tests for a Schesch human sample solution. The command checks out the "
            "merge commit as the human resolution, asks opencode to create tests once per "
            "content-conflicting file, stores a git format-patch result in Redis, and leaves "
            "coverage empty for future assessment."
        )
    )
    parser.add_argument("repo_name", help="Bare repository cache key, e.g. owner/repo.git")
    parser.add_argument("merge_sha", nargs="?", help="Merge commit SHA containing the human sample solution")
    parser.add_argument(
        "--parents",
        nargs=2,
        metavar=("LEFT_SHA", "RIGHT_SHA"),
        help="Resolve the merge commit from a Schesch parent pair when merge_sha is omitted.",
    )
    parser.add_argument(
        "--opencode",
        default=os.environ.get("OPENCODE", DEFAULT_OPENCODE_EXECUTABLE),
        help="Path to the opencode executable.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_OPENCODE_TIMEOUT_SECONDS,
        help="Timeout in seconds for each per-file opencode run.",
    )
    parser.add_argument("--keep-playground", action="store_true", help="Do not delete the playground after generation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout < 1:
        logger.error("--timeout must be at least 1")
        return 1
    if args.merge_sha and args.parents:
        logger.error("Specify either merge_sha or --parents, not both")
        return 1
    if not args.merge_sha and not args.parents:
        logger.error("Specify merge_sha or --parents")
        return 1

    try:
        if args.parents:
            logger.info(
                "Resolving merge commit for {} from parent pair {} {}",
                args.repo_name,
                args.parents[0],
                args.parents[1],
            )
        merge_sha = args.merge_sha or resolve_unique_merge_sha_from_parents(args.repo_name, tuple(args.parents))
        logger.info("Using merge commit {}", merge_sha)
        record = generate_tests(
            setup_redis_connection(),
            args.repo_name,
            merge_sha,
            opencode_executable=args.opencode,
            timeout_seconds=args.timeout,
            keep_playground=args.keep_playground,
        )
    except (RuntimeError, subprocess.CalledProcessError) as error:
        logger.error("{}", error)
        return 1

    test_execution_success = bool(record.human and record.human.get("passed"))
    print(record.redis_key)
    print(f"test_execution_success={'true' if test_execution_success else 'false'}")
    return 0 if record.error is None else 1


if __name__ == "__main__":
    sys.exit(main())
