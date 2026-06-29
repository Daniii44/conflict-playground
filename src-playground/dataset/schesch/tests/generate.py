#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from common.git_util import capture_git, git_env
from common.merge_tree import ConflictType
from common.redis_util import setup_redis_connection
from info.conflict.analysis.core_analysis import InfoConflictCore
from playbook.playgrounds import resolve_merge_sha_from_parents
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
    patch: str | None = None
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
        "- The worktree is checked out at the human sample solution. Treat the current contents "
        "of the target file as the reference behavior.\n"
        "- Only generate or update tests needed to exercise that resolved behavior. Do not edit "
        "production source files unless a test framework requires a minimal fixture/configuration change.\n"
        "- Keep the change scoped to this file's resolved behavior; do not generate tests for other "
        "conflicting files in this run.\n\n"
        "Conflict metadata for this file:\n"
        f"{conflict_json}\n"
    )


def prepare_human_solution_worktree(playground_path: Path, merge_sha: str) -> None:
    commands = (
        ("reset", "--hard"),
        ("clean", "-fdx"),
        ("checkout", "--force", "-B", "schesch-test-generation", merge_sha),
        ("reset", "--hard"),
        ("clean", "-fdx"),
    )
    for command in commands:
        capture_git("-C", str(playground_path), *command)


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


def format_generated_patch(playground_path: Path, base_ref: str) -> str | None:
    result = capture_git(
        "-C",
        str(playground_path),
        "format-patch",
        "--stdout",
        f"{base_ref}..HEAD",
    )
    patch = result.stdout
    return patch if patch.strip() else None


def load_conflict_info(redis, repo_name: str, merge_sha: str) -> InfoConflictCore:
    key = conflict_info_key(repo_name, merge_sha)
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No info:core conflict record found at {key}")
    return InfoConflictCore.model_validate(payload)


def store_generation(redis, record: ScheschGeneratedTests) -> None:
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

        playground_name = setup_playground(repo_name, merge_sha)
        record.playground_name = playground_name
        playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
        playground_path = playgrounds / playground_name
        prepare_human_solution_worktree(playground_path, merge_sha)

        for file_path in paths:
            prompt = prompt_for_file(conflict_info, file_path)
            exit_code, tail, error, duration = run_opencode_for_file(
                playground_path,
                opencode_executable,
                prompt,
                timeout_seconds,
            )
            record.files.append(
                GeneratedTestFile(
                    path=file_path,
                    prompt=prompt,
                    duration_seconds=duration,
                    opencode_exit_code=exit_code,
                    output_tail=tail,
                    error=error,
                )
            )
            if error is not None:
                raise RuntimeError(f"Test generation failed for {file_path}: {error}")

        record.test_commit_sha = commit_generated_tests(playground_path)
        record.patch = format_generated_patch(playground_path, merge_sha) if record.test_commit_sha else None
        if record.patch is None:
            record.error = "opencode completed but did not create any test changes"
    except Exception as error:
        record.error = str(error)
        logger.error("{}", error)
    finally:
        record.duration_seconds = time.monotonic() - started_at
        store_generation(redis, record)
        if playground_path is not None and not keep_playground:
            shutil.rmtree(playground_path, ignore_errors=True)

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
        merge_sha = args.merge_sha or resolve_merge_sha_from_parents(args.repo_name, tuple(args.parents))
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

    print(record.redis_key)
    return 0 if record.error is None else 1


if __name__ == "__main__":
    sys.exit(main())
