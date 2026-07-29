#!/usr/bin/env python3

import argparse
import os
import random
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from common.redis_util import setup_redis_connection
from dataset.schesch.playbook import default_playbook_output_path
from dataset.schesch.tests.generate import (
    DEFAULT_OPENCODE_EXECUTABLE,
    DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    ScheschGeneratedTests,
    generate_tests,
    generated_patch_bytes,
    generated_tests_record_key,
    validate_generated_patch,
)
from playbook.playgrounds import (
    Playground,
    load_playbook_result,
    resolve_playground_merge_sha,
)


@dataclass
class MissingGenerationResult:
    total: int = 0
    skipped: int = 0
    generated: int = 0
    failed: int = 0
    failed_keys: list[str] = field(default_factory=list)


def load_generated_tests_record(redis, key: str) -> ScheschGeneratedTests | None:
    payload = redis.json().get(key)
    if not payload:
        return None

    try:
        return ScheschGeneratedTests.model_validate(payload)
    except Exception as error:
        logger.warning("Regenerating tests because existing record {} is invalid: {}", key, error)
        return None


def generation_attempt_count(record: ScheschGeneratedTests | None) -> int:
    if record is None:
        return 0
    return record.regeneration_count + 1


def has_usable_generated_test_record(record: ScheschGeneratedTests | None) -> bool:
    if record is None:
        return False

    patch_bytes = generated_patch_bytes(record)
    if record.error is not None or patch_bytes is None:
        return False

    selectors, patch_error = validate_generated_patch(patch_bytes)
    return patch_error is None and bool(selectors)


def has_usable_generated_tests(redis, key: str) -> bool:
    return has_usable_generated_test_record(load_generated_tests_record(redis, key))


def selected_playgrounds(
    playbook_path: Path,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[Playground]:
    playgrounds = load_playbook_result(playbook_path).playgrounds
    if skip > 0:
        playgrounds = playgrounds[skip:]
    if limit is not None:
        playgrounds = playgrounds[:limit]
    return playgrounds


def generate_missing_tests_for_playbook(
    redis,
    playbook_path: Path,
    *,
    opencode_executable: str = DEFAULT_OPENCODE_EXECUTABLE,
    timeout_seconds: int = DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    keep_playground: bool = False,
    skip: int = 0,
    limit: int | None = None,
    max_attempts: int = 3,
    stop_on_error: bool = False,
) -> MissingGenerationResult:
    selected = selected_playgrounds(playbook_path, skip=skip, limit=limit)
    pending_playgrounds: list[tuple[Playground, str, str]] = []
    skipped = 0
    for playground in selected:
        merge_sha = resolve_playground_merge_sha(playground)
        key = generated_tests_record_key(playground.repo_name, merge_sha)
        record = load_generated_tests_record(redis, key)
        if has_usable_generated_test_record(record):
            skipped += 1
            logger.info("Pruning {}; generated tests already exist at {}", playground.target_label(), key)
            continue
        attempts = generation_attempt_count(record)
        if record is not None and attempts >= max_attempts:
            skipped += 1
            logger.info(
                "Pruning {}; generation attempts reached {} at {}",
                playground.target_label(),
                max_attempts,
                key,
            )
            continue
        pending_playgrounds.append((playground, merge_sha, key))

    result = MissingGenerationResult(total=len(pending_playgrounds), skipped=skipped)
    random.shuffle(pending_playgrounds)
    logger.info(
        "Loaded {} conflicts from playbook {} (skip={}, limit={}); {} remain after pruning {} existing records",
        len(selected),
        playbook_path,
        skip,
        limit,
        result.total,
        result.skipped,
    )

    for index, (playground, merge_sha, key) in enumerate(pending_playgrounds, start=1):
        logger.info(
            "Processing playbook conflict {}/{}: {} {}",
            index,
            len(pending_playgrounds),
            playground.repo_name,
            playground.target_label(),
        )

        record = generate_tests(
            redis,
            playground.repo_name,
            merge_sha,
            opencode_executable=opencode_executable,
            timeout_seconds=timeout_seconds,
            keep_playground=keep_playground,
        )
        if record.error is None:
            result.generated += 1
            logger.info("Generated tests for {} {} at {}", playground.repo_name, merge_sha, key)
        else:
            result.failed += 1
            result.failed_keys.append(key)
            logger.error("Failed to generate tests for {} {}: {}", playground.repo_name, merge_sha, record.error)
            if stop_on_error:
                break

    logger.info(
        "Finished playbook test generation: total={}, generated={}, skipped={}, failed={}",
        result.total,
        result.generated,
        result.skipped,
        result.failed,
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Schesch test suites for every conflict in the Schesch playbook that does not "
            "already have a usable generated-test Redis record."
        )
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
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N playbook conflicts.")
    parser.add_argument("--limit", type=int, help="Generate at most N playbook conflicts after --skip.")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Skip conflicts that already have this many generation attempts recorded.",
    )
    parser.add_argument("--keep-playground", action="store_true", help="Do not delete playgrounds after generation.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop after the first generation failure.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout < 1:
        logger.error("--timeout must be at least 1")
        return 1
    if args.skip < 0:
        logger.error("--skip must not be negative")
        return 1
    if args.limit is not None and args.limit < 1:
        logger.error("--limit must be at least 1")
        return 1
    if args.max_attempts < 1:
        logger.error("--max-attempts must be at least 1")
        return 1

    try:
        playbook_path = default_playbook_output_path()
        if not playbook_path.is_file():
            logger.error("Schesch playbook does not exist: {}", playbook_path)
            return 1

        result = generate_missing_tests_for_playbook(
            setup_redis_connection(),
            playbook_path,
            opencode_executable=args.opencode,
            timeout_seconds=args.timeout,
            keep_playground=args.keep_playground,
            skip=args.skip,
            limit=args.limit,
            max_attempts=args.max_attempts,
            stop_on_error=args.stop_on_error,
        )
    except (RuntimeError, subprocess.CalledProcessError) as error:
        logger.error("{}", error)
        return 1

    print(
        f"total={result.total} generated={result.generated} "
        f"skipped={result.skipped} failed={result.failed}"
    )
    for key in result.failed_keys:
        print(f"failed={key}")

    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
