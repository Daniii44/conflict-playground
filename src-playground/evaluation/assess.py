#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
import os
import subprocess

import rich
from common.active_playground_models import Configuration, ActivePlayground
from common.evaluation_models import Evaluation, ConflictEvaluation, ProposedResolution
from common.git_util import capture_git
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

def collect_proposed_resolution(playground_name: str) -> ProposedResolution:
    playgrounds = os.environ.get("PLAYGROUNDS")
    if playgrounds is None:
        return ProposedResolution(error="PLAYGROUNDS environment variable is not set")

    playground_path = f"{playgrounds}/{playground_name}"
    head_result = capture_git("-C", playground_path, "rev-parse", "HEAD", check=False)
    if head_result.returncode != 0:
        error = head_result.stderr.strip() or head_result.stdout.strip()
        return ProposedResolution(error=f"Could not read resolved HEAD: {error}")

    commit_sha = head_result.stdout.strip()
    show_result = capture_git("-C", playground_path, "show", "--cc", commit_sha, check=False)
    if show_result.returncode != 0:
        error = show_result.stderr.strip() or show_result.stdout.strip()
        return ProposedResolution(
            commit_sha=commit_sha,
            error=f"Could not export proposed resolution with git show --cc: {error}",
        )

    return ProposedResolution(commit_sha=commit_sha, show_cc=show_result.stdout)

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
    proposed_resolution = collect_proposed_resolution(args.playground_name)
    conflict_evaluation = ConflictEvaluation(
        configuration=active_playground.configuration,
        result=evaluation,
        hook_result=active_playground.hook_result,
        proposed_resolution=proposed_resolution,
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
