#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

from loguru import logger

from common.evaluation_models import ConflictEvaluation, Evaluation, ProposedResolution
from common.redis_util import (
    EVALUATION_CONFLICT_PREFIX,
    RESOLUTION_CONFLICT_PREFIX,
    setup_redis_connection,
)
from common.resolution_models import ConflictResolution
from evaluation.assess import (
    collect_proposed_resolution,
    duration_seconds,
    evaluate,
    evaluation_record_key,
)


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def playground_name_from_resolution_key(resolution_key: str) -> str:
    return resolution_key_parts(resolution_key)[0]


def resolution_key_parts(resolution_key: str) -> tuple[str, str]:
    suffix = resolution_key.removeprefix(RESOLUTION_CONFLICT_PREFIX)
    playground_name, resolution_timestamp = suffix.rsplit(":", 1)
    return playground_name, resolution_timestamp


def restored_playground_name_from_resolution_key(resolution_key: str) -> str:
    playground_name, resolution_timestamp = resolution_key_parts(resolution_key)
    repo_name, merge_sha = playground_name.rsplit("-", 1)
    return f"{repo_name}-{resolution_timestamp}-{merge_sha}"


def iter_resolution_keys(redis, playground_name: str | None = None) -> list[str]:
    if playground_name is None:
        match = f"{RESOLUTION_CONFLICT_PREFIX}*"
    else:
        match = f"{RESOLUTION_CONFLICT_PREFIX}{playground_name}:*"

    return sorted(normalize_key(key) for key in redis.scan_iter(match=match))


def evaluated_resolution_keys(redis) -> set[str]:
    resolution_keys = set()
    for key in redis.scan_iter(match=f"{EVALUATION_CONFLICT_PREFIX}*"):
        evaluation_data = redis.json().get(normalize_key(key))
        if not evaluation_data:
            continue

        resolution_key = evaluation_data.get("resolution_key")
        if resolution_key:
            resolution_keys.add(resolution_key)

    return resolution_keys


def restore_resolution(playground_name: str, git_archive: str) -> None:
    result = subprocess.run(
        ["playground-restore", playground_name],
        input=git_archive,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Could not restore resolution archive: {error}")


def failed_evaluation(
    resolution: ConflictResolution,
    error: str,
    resolution_key: str,
) -> ConflictEvaluation:
    return ConflictEvaluation(
        resolution_key=resolution_key,
        configuration=resolution.configuration,
        result=Evaluation(
            duration_seconds=duration_seconds(
                resolution.configuration,
                resolution.resolution_end,
            ),
            incomplete_merge=True,
            perfect_match=False,
        ),
        hook_result=resolution.hook_result,
        proposed_resolution=ProposedResolution(error=error),
    )


def evaluate_resolution(resolution_key: str, resolution: ConflictResolution) -> ConflictEvaluation:
    playground_name = restored_playground_name_from_resolution_key(resolution_key)
    proposed_resolution = resolution.proposed_resolution
    if proposed_resolution is None:
        return failed_evaluation(resolution, "Resolution has no proposed_resolution", resolution_key)

    if proposed_resolution.git_archive is None:
        error = proposed_resolution.error or "Resolution has no archived .git repository"
        return failed_evaluation(resolution, error, resolution_key)

    try:
        restore_resolution(playground_name, proposed_resolution.git_archive)
    except RuntimeError as error:
        return failed_evaluation(resolution, str(error), resolution_key)

    result = evaluate(
        resolution.configuration,
        playground_name,
        resolution_end=resolution.resolution_end,
    )
    analyzed_resolution = collect_proposed_resolution(playground_name)

    return ConflictEvaluation(
        resolution_key=resolution_key,
        configuration=resolution.configuration,
        result=result,
        hook_result=resolution.hook_result,
        proposed_resolution=analyzed_resolution,
    )


def store_evaluation(redis, playground_name: str, evaluation: ConflictEvaluation) -> str:
    evaluation_key = evaluation_record_key(playground_name, datetime.now(timezone.utc))
    redis.json().set(evaluation_key, "$", json.loads(evaluation.model_dump_json()))
    return evaluation_key


def evaluate_resolution_key(redis, resolution_key: str) -> str:
    resolution_data = redis.json().get(resolution_key)
    if not resolution_data:
        raise RuntimeError(f"No resolution found at {resolution_key}")

    resolution = ConflictResolution.model_validate(resolution_data)
    playground = playground_name_from_resolution_key(resolution_key)
    evaluation = evaluate_resolution(resolution_key, resolution)
    return store_evaluation(redis, playground, evaluation)


def sync_evaluations(playground_name: str | None = None, force: bool = False) -> int:
    redis = setup_redis_connection()
    resolution_keys = iter_resolution_keys(redis, playground_name)
    already_evaluated = set() if force else evaluated_resolution_keys(redis)
    synced = 0

    for resolution_key in resolution_keys:
        if resolution_key in already_evaluated:
            logger.info("Skipping already evaluated resolution {}", resolution_key)
            continue

        evaluation_key = evaluate_resolution_key(redis, resolution_key)
        logger.info("Stored evaluation at {}", evaluation_key)
        synced += 1

    logger.info("Evaluation sync complete: {} created", synced)
    return synced


def main() -> int:
    parser = argparse.ArgumentParser(description="Create evaluation records from saved conflict resolutions")
    parser.add_argument("playground_name", nargs="?", help="Only evaluate resolutions for this playground")
    parser.add_argument("--force", action="store_true", help="Create a new evaluation even when one already links to the resolution")
    args = parser.parse_args()

    try:
        sync_evaluations(args.playground_name, force=args.force)
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
