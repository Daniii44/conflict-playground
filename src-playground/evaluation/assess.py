#!/usr/bin/env python3

import argparse
from datetime import datetime
import os
import sys

import rich
from common.active_playground_models import ActivePlayground, Configuration
from common.evaluation_models import MergeCoreEvaluation
from common.redis_util import RUNTIME_ACTIVE_PLAYGROUND_PREFIX, setup_redis_connection
from evaluation.analysis.common import actual_resolution_sha_from_playground_name, read_head_commit
from evaluation.analysis.core_analysis import duration_seconds, evaluation_check_for_merge, evaluation_diff


def evaluate(
    configuration: Configuration,
    playground_name: str,
    resolution_end: datetime | None = None,
) -> MergeCoreEvaluation:
    if resolution_end is None:
        resolution_end = datetime.now()

    playgrounds = os.environ.get("PLAYGROUNDS")
    playground_path = f"{playgrounds}/{playground_name}" if playgrounds is not None else playground_name
    proposed_commit_sha, head_error = read_head_commit(playground_path)

    evaluation = MergeCoreEvaluation(
        resolution_key=f"active:{playground_name}",
        duration_seconds=duration_seconds(configuration, resolution_end),
        incomplete_merge=False,
        perfect_match=False,
        proposed_commit_sha=proposed_commit_sha,
        actual_resolution_sha=actual_resolution_sha_from_playground_name(playground_name),
        error=head_error,
    )

    if not evaluation_check_for_merge(playground_name):
        evaluation.incomplete_merge = True
        return evaluation

    if not evaluation_diff(playground_name):
        evaluation.perfect_match = False
        return evaluation

    evaluation.perfect_match = True
    return evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess an active conflict-resolution playground")
    parser.add_argument("playground_name", help="Name of the playground to assess")
    args = parser.parse_args()

    redis = setup_redis_connection()

    active_playground_data = redis.json().get(f"{RUNTIME_ACTIVE_PLAYGROUND_PREFIX}{args.playground_name}")
    if not active_playground_data:
        print(f"No active playground found with name {args.playground_name}")
        return 1
    active_playground = ActivePlayground.model_validate(active_playground_data)

    evaluation = evaluate(active_playground.configuration, args.playground_name)
    print(f"Evaluation result for {args.playground_name}:")
    rich.print_json(evaluation.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
