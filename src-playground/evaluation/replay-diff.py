#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from common.evaluation_models import ConflictEvaluation
from common.redis_util import EVALUATION_CONFLICT_PREFIX, setup_redis_connection


def latest_evaluation_key(redis, playground_name: str) -> str | None:
    legacy_key = f"{EVALUATION_CONFLICT_PREFIX}{playground_name}"
    if redis.exists(legacy_key):
        return legacy_key

    keys = list(redis.scan_iter(match=f"{legacy_key}:*"))
    if not keys:
        return None
    return max(key.decode() if isinstance(key, bytes) else key for key in keys)


def replay_diff(playground_name: str) -> int:
    redis = setup_redis_connection()
    key = latest_evaluation_key(redis, playground_name)
    if key is None:
        logger.error("No evaluation found for playground {}", playground_name)
        return 1

    evaluation_data = redis.json().get(key)
    if not evaluation_data:
        logger.error("No evaluation found for playground {}", playground_name)
        return 1

    evaluation = ConflictEvaluation.model_validate(evaluation_data)
    proposed_resolution = evaluation.proposed_resolution
    if proposed_resolution is None:
        logger.error("Evaluation for playground {} has no proposed resolution", playground_name)
        return 1

    diff = proposed_resolution.diff_to_actual_resolution
    if diff is None:
        if proposed_resolution.error:
            logger.error("Proposed resolution diff was not recorded: {}", proposed_resolution.error)
        else:
            logger.error("Evaluation for playground {} has no recorded proposed resolution diff", playground_name)
        return 1

    sys.stdout.write(diff)
    if diff and not diff.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded proposed-resolution diff")
    parser.add_argument("playground_name", help="Name of the assessed playground")
    args = parser.parse_args()

    return replay_diff(args.playground_name)


if __name__ == "__main__":
    sys.exit(main())
