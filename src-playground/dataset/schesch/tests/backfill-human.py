#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from common.evaluation_models import ScheschResolutionResult
from common.redis_util import setup_redis_connection
from common.schesch import ScheschResolutionRunner, reset_playground
from dataset.schesch.tests.apply import apply_patch_to_current_head
from dataset.schesch.tests.generate import (
    DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    ScheschGeneratedTests,
    TEST_GENERATION_PREFIX,
    expected_human_java_home,
    generated_patch_bytes,
    generated_test_command,
    store_generation,
    validate_generated_patch,
)
from playground.setup import setup_playground


@dataclass
class BackfillHumanResult:
    total: int = 0
    skipped: int = 0
    updated: int = 0
    failed: int = 0
    failed_keys: list[str] = field(default_factory=list)


def generated_test_keys(redis, limit: int | None = None) -> list[str]:
    keys = sorted(str(key) for key in redis.scan_iter(match=f"{TEST_GENERATION_PREFIX}*"))
    if limit is not None:
        return keys[:limit]
    return keys


def load_generated_test_record(redis, key: str) -> ScheschGeneratedTests:
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No generated Schesch test suite found at {key}")
    return ScheschGeneratedTests.model_validate(payload)


def attempted_human_result(error: str, commit_sha: str | None) -> ScheschResolutionResult:
    return ScheschResolutionResult(
        label="human",
        commit_sha=commit_sha,
        error=error,
    )


def backfill_human_result(
    redis,
    record: ScheschGeneratedTests,
    *,
    timeout_seconds: int = DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    keep_playground: bool = False,
) -> ScheschResolutionResult:
    patch_bytes = generated_patch_bytes(record)
    if patch_bytes is None:
        return attempted_human_result("Generated test suite has no patch", record.human_solution_ref)

    selectors, patch_error = validate_generated_patch(patch_bytes)
    if patch_error is not None:
        return attempted_human_result(patch_error, record.human_solution_ref)

    playground_name = setup_playground(record.repo, record.merge_sha)
    playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
    playground_path = playgrounds / playground_name

    try:
        reset_error = reset_playground(playground_path, record.human_solution_ref)
        if reset_error is not None:
            return attempted_human_result(
                f"Could not reset playground to {record.human_solution_ref}: {reset_error}",
                record.human_solution_ref,
            )

        apply_patch_to_current_head(playground_path, patch_bytes)
        java_home = expected_human_java_home(redis, record.repo, record.merge_sha)
        test_command, build_tool = generated_test_command(playground_path, selectors, timeout_seconds)
        result = ScheschResolutionRunner(timeout_seconds=timeout_seconds).run_tests_in_current_state(
            playground_path,
            "human",
            commit_sha=record.human_solution_ref,
            java_homes=[java_home],
            test_command=test_command,
        )
        result.build_tool = result.build_tool or build_tool
        return result
    except RuntimeError as error:
        return attempted_human_result(str(error), record.human_solution_ref)
    finally:
        if not keep_playground:
            logger.info("Removing playground {}", playground_path)
            shutil.rmtree(playground_path, ignore_errors=True)
        else:
            logger.info("Keeping playground {}", playground_path)


def backfill_missing_human_records(
    redis,
    *,
    timeout_seconds: int = DEFAULT_OPENCODE_TIMEOUT_SECONDS,
    keep_playground: bool = False,
    limit: int | None = None,
    stop_on_error: bool = False,
) -> BackfillHumanResult:
    keys = generated_test_keys(redis, limit=limit)
    result = BackfillHumanResult(total=len(keys))

    for index, key in enumerate(keys, start=1):
        logger.info("Processing generated Schesch test record {}/{}: {}", index, len(keys), key)
        try:
            record = load_generated_test_record(redis, key)
        except Exception as error:
            result.failed += 1
            result.failed_keys.append(key)
            logger.error("Failed to load generated Schesch test record {}: {}", key, error)
            if stop_on_error:
                break
            continue

        if record.human is not None:
            result.skipped += 1
            logger.info("Skipping {}; human backfill already exists", key)
            continue

        try:
            record.human = backfill_human_result(
                redis,
                record,
                timeout_seconds=timeout_seconds,
                keep_playground=keep_playground,
            ).model_dump(mode="json")
            store_generation(redis, record)
            result.updated += 1
            logger.info("Backfilled human Schesch result for {}", key)
        except KeyboardInterrupt:
            logger.info("Interrupted while backfilling {}", key)
            raise
        except Exception as error:
            result.failed += 1
            result.failed_keys.append(key)
            logger.error("Failed to backfill human Schesch result for {}: {}", key, error)
            if stop_on_error:
                break

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill the `human` Schesch test execution record on early generated-test Redis entries "
            "that predate the current generator verification flow."
        )
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_OPENCODE_TIMEOUT_SECONDS,
        help="Timeout in seconds for each backfilled human test execution.",
    )
    parser.add_argument("--limit", type=int, help="Backfill at most N generated-test records.")
    parser.add_argument("--keep-playground", action="store_true", help="Do not delete playgrounds after backfill.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop after the first backfill failure.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout < 1:
        logger.error("--timeout must be at least 1")
        return 1
    if args.limit is not None and args.limit < 1:
        logger.error("--limit must be at least 1")
        return 1

    try:
        result = backfill_missing_human_records(
            setup_redis_connection(),
            timeout_seconds=args.timeout,
            keep_playground=args.keep_playground,
            limit=args.limit,
            stop_on_error=args.stop_on_error,
        )
    except (RuntimeError, subprocess.CalledProcessError) as error:
        logger.error("{}", error)
        return 1

    print(
        f"total={result.total} updated={result.updated} "
        f"skipped={result.skipped} failed={result.failed}"
    )
    for key in result.failed_keys:
        print(f"failed={key}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
