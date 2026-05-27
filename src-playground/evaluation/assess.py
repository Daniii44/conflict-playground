#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
import subprocess

import rich
from common.active_playground_models import Configuration, ActivePlayground
from common.evaluation_models import Evaluation, ConflictEvaluation
from common.redis_util import (
    EVALUATION_CONFLICT_PREFIX,
    RUNTIME_ACTIVE_PLAYGROUND_PREFIX,
    setup_redis_connection,
)


def evaluation_check_for_merge(playground_name: str) -> bool:
    """Check if all commits can be merged without conflicts"""
    try:
        subprocess.run(["evaluation-check-for-merge", playground_name], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def evaluation_diff(playground_name: str) -> bool:
    """Check if there are any conflicts in the merged result"""
    try:
        subprocess.run(["evaluation-diff", playground_name], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def evaluate(configuration: Configuration, playground_name: str) -> Evaluation:
    print(configuration.resolution_start)
    print(datetime.now())
    evaluation = Evaluation(
        duration_seconds=(datetime.now() - configuration.resolution_start).total_seconds(),
        incomplete_merge=False,
        perfect_match=False
    )

    if not evaluation_check_for_merge(playground_name):
        evaluation.incomplete_merge = True
        return evaluation
    else:
        evaluation.incomplete_merge = False

    if not evaluation_diff(playground_name):
        evaluation.perfect_match = False
        return evaluation
    else:
        evaluation.perfect_match = True

    return evaluation

def main():
    parser = argparse.ArgumentParser(description="Assess Conflict Resolution")
    parser.add_argument("playground_name", help="Name of the playground to assess")
    args = parser.parse_args()

    redis = setup_redis_connection()

    active_playground_data = redis.json().get(f"{RUNTIME_ACTIVE_PLAYGROUND_PREFIX}{args.playground_name}")
    if not active_playground_data:
        print(f"No active playground found with name {args.playground_name}")
        return
    active_playground = ActivePlayground.model_validate(active_playground_data)

    print(f"Assessing playground {args.playground_name} with config: {active_playground}")

    evaluation = evaluate(active_playground.configuration, args.playground_name)
    conflict_evaluation = ConflictEvaluation(
        configuration=active_playground.configuration,
        result=evaluation,
        hook_result=active_playground.hook_result,
    )
    redis.json().set(
        f"{EVALUATION_CONFLICT_PREFIX}{args.playground_name}",
        "$",
        json.loads(conflict_evaluation.model_dump_json()),
    )
    print(f"Evaluation result for {args.playground_name}:")
    rich.print_json(conflict_evaluation.model_dump_json())


if __name__ == "__main__":
    main()
