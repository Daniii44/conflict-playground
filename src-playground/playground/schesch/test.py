#!/usr/bin/env python3

import os
import sys
from pathlib import Path

from loguru import logger

from common.git_util import capture_git
from common.redis_util import setup_redis_connection
from common.schesch import (
    ScheschResolutionRunner,
    determine_expected_java_home,
    java_home_env_var,
    parse_schesch_playground_name,
    schesch_info_key,
)


def resolve_playground_root() -> Path:
    result = capture_git("rev-parse", "--show-toplevel", check=False, cwd=Path.cwd())
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Current directory is not inside a playground git worktree: {error}")
    return Path(result.stdout.strip())


def expected_java_home_for_playground(redis, playground_path: Path) -> tuple[str, str, str]:
    repo_name, merge_sha = parse_schesch_playground_name(playground_path.name)
    key = schesch_info_key(repo_name, merge_sha)
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No Schesch info record found at {key}")

    java_home, error = determine_expected_java_home(payload)
    if error is not None or java_home is None:
        raise RuntimeError(f"Could not determine expected Java home from {key}: {error}")
    return repo_name, merge_sha, java_home


def run_playground_schesch_test() -> int:
    playground_path = resolve_playground_root()
    repo_name, merge_sha, java_home = expected_java_home_for_playground(setup_redis_connection(), playground_path)
    java_home_name = java_home_env_var(java_home) or java_home
    logger.info(
        "Running Schesch tests for playground {} (repo={} merge={}) with {}",
        playground_path.name,
        repo_name,
        merge_sha,
        java_home_name,
    )

    record = ScheschResolutionRunner(stream_output=True).run_tests_in_current_state(
        playground_path,
        "playground",
        java_homes=[java_home],
    )
    if record.error is not None:
        logger.error("{}", record.error)
    if record.passed:
        logger.info("Schesch tests passed with {}", java_home_name)
        return 0
    if record.compilation_failed:
        logger.error("Compilation failed with {}", java_home_name)
        return 1
    if record.test_execution_failed:
        logger.error("Tests failed with {}", java_home_name)
        return 1
    if record.timed_out:
        logger.error("Schesch tests timed out with {}", java_home_name)
        return 1

    logger.error("Schesch tests did not pass with {}", java_home_name)
    return 1


def main() -> int:
    try:
        return run_playground_schesch_test()
    except RuntimeError as error:
        logger.error("{}", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
