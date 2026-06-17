#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from common.evaluation_models import MergeDiffEvaluation
from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection
from evaluation.analysis.common import evaluation_record_key


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def latest_resolution_key(redis, playground_name: str) -> str | None:
    keys = list(redis.scan_iter(match=f"{RESOLUTION_CONFLICT_PREFIX}{playground_name}:*"))
    if not keys:
        return None
    return max(normalize_key(key) for key in keys)


def diff_evaluation_key(redis, resolution_or_playground: str) -> str | None:
    if resolution_or_playground.startswith(RESOLUTION_CONFLICT_PREFIX):
        return evaluation_record_key("diff", resolution_or_playground)

    resolution_key = latest_resolution_key(redis, resolution_or_playground)
    if resolution_key is None:
        return None
    return evaluation_record_key("diff", resolution_key)


def recorded_proposed_to_actual_patch(evaluation: MergeDiffEvaluation, evaluation_data) -> str | None:
    default_diff = evaluation.proposed_to_actual_resolution_diffs.get("exact", {}).get("include_blank_lines")
    if default_diff is not None and default_diff.patch is not None:
        return default_diff.patch

    if evaluation.proposed_to_actual_resolution_patch is not None:
        return evaluation.proposed_to_actual_resolution_patch

    if isinstance(evaluation_data, dict):
        return evaluation_data.get("diff_to_actual_resolution")

    return None


def replay_diff(resolution_or_playground: str) -> int:
    redis = setup_redis_connection()
    key = diff_evaluation_key(redis, resolution_or_playground)
    if key is None:
        logger.error("No saved resolution found for {}", resolution_or_playground)
        return 1

    evaluation_data = redis.json().get(key)
    if not evaluation_data:
        logger.error("No diff evaluation found at {}", key)
        return 1

    evaluation = MergeDiffEvaluation.model_validate(evaluation_data)
    diff = recorded_proposed_to_actual_patch(evaluation, evaluation_data)
    if diff is None:
        if evaluation.error:
            logger.error("Proposed resolution diff was not recorded: {}", evaluation.error)
        else:
            logger.error("Diff evaluation at {} has no recorded proposed resolution diff", key)
        return 1

    sys.stdout.write(diff)
    if diff and not diff.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded proposed-resolution diff")
    parser.add_argument("resolution_or_playground", help="Saved resolution key or playground name")
    args = parser.parse_args()

    return replay_diff(args.resolution_or_playground)


if __name__ == "__main__":
    sys.exit(main())
