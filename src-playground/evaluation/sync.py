#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys

from loguru import logger

from common.evaluation_models import EvaluationInput
from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection
from common.resolution_models import ConflictResolution, resolution_key_parts
from evaluation.analysis.common import (
    EvaluationAnalysis,
    evaluation_record_key,
    resolution_postfix,
)
from evaluation.analysis.classification_analysis import ClassificationEvaluationAnalysis
from evaluation.analysis.core_analysis import CoreEvaluationAnalysis
from evaluation.analysis.diff_analysis import DiffEvaluationAnalysis
from evaluation.analysis.sem_analysis import SemEvaluationAnalysis
from evaluation.analysis.schesch_generated_analysis import ScheschGeneratedEvaluationAnalysis
from evaluation.analysis.schesch_original_analysis import ScheschOriginalEvaluationAnalysis
from evaluation.analysis.summary_analysis import SummaryEvaluationAnalysis
from evaluation.analysis.modifydelete_analysis import ModifyDeleteEvaluationAnalysis
from evaluation.analysis.rename_analysis import RenameEvaluationAnalysis


AVAILABLE_ANALYSES: dict[str, type[EvaluationAnalysis]] = {
    "core": CoreEvaluationAnalysis,
    "diff": DiffEvaluationAnalysis,
    "sem": SemEvaluationAnalysis,
    "classification": ClassificationEvaluationAnalysis,
    "schesch-original": ScheschOriginalEvaluationAnalysis,
    "schesch-generated": ScheschGeneratedEvaluationAnalysis,
    "summary": SummaryEvaluationAnalysis,
    "modifydelete": ModifyDeleteEvaluationAnalysis,
    "rename": RenameEvaluationAnalysis,
}


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def restored_playground_name_from_resolution_key(resolution_key: str) -> str:
    playground_name, resolution_timestamp = resolution_key_parts(resolution_key)
    repo_name, merge_sha = playground_name.rsplit("-", 1)
    return f"{repo_name}-{resolution_timestamp}-{merge_sha}"


def iter_resolution_keys(redis) -> list[str]:
    return sorted(normalize_key(key) for key in redis.scan_iter(match=f"{RESOLUTION_CONFLICT_PREFIX}*"))


def collect_analyses(analyses: list[str]) -> list[EvaluationAnalysis]:
    collected = []
    for analysis_name in analyses:
        analysis_type = AVAILABLE_ANALYSES.get(analysis_name)
        if analysis_type is None:
            raise RuntimeError(
                f"No such analysis: {analysis_name}; available analyses: {', '.join(AVAILABLE_ANALYSES)}"
            )
        collected.append(analysis_type(analysis_name))
    return collected


def analysis_result_exists(redis, analysis_name: str, resolution_key: str) -> bool:
    return bool(redis.exists(evaluation_record_key(analysis_name, resolution_key)))


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


def remove_restored_playground(playground_name: str) -> str | None:
    result = subprocess.run(
        ["playground-rm", playground_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()
    return None


def evaluation_input_for_resolution(
    resolution_key: str,
    resolution: ConflictResolution,
) -> EvaluationInput:
    return EvaluationInput(
        resolution_key=resolution_key,
        resolution_postfix=resolution_postfix(resolution_key),
        restored_playground_name=restored_playground_name_from_resolution_key(resolution_key),
        resolution=resolution,
    )


def resolution_has_error(resolution: ConflictResolution) -> bool:
    proposed_resolution = resolution.proposed_resolution
    return proposed_resolution is not None and proposed_resolution.error is not None


def restore_resolution_for_analysis(evaluation_input: EvaluationInput) -> tuple[str | None, bool]:
    proposed_resolution = evaluation_input.resolution.proposed_resolution
    if proposed_resolution is None:
        return "Resolution has no proposed_resolution", False

    if proposed_resolution.git_archive is None:
        return proposed_resolution.error or "Resolution has no archived .git repository", False

    try:
        restore_resolution(
            evaluation_input.restored_playground_name,
            proposed_resolution.git_archive,
        )
    except RuntimeError as error:
        return str(error), True

    return None, True


def evaluate_resolution(
    resolution_key: str,
    resolution: ConflictResolution,
    analyses: list[EvaluationAnalysis],
) -> list[tuple[str, object]]:
    evaluation_input = evaluation_input_for_resolution(resolution_key, resolution)
    restore_error, restored = restore_resolution_for_analysis(evaluation_input)

    try:
        results = []
        for analysis in analyses:
            if restore_error is not None and hasattr(analysis, "failed"):
                analysis_output = analysis.failed(evaluation_input, restore_error)
            else:
                analysis_output = analysis.analyse(evaluation_input)

            if analysis_output is not None:
                key = evaluation_record_key(analysis, resolution_key)
                results.append((key, analysis_output))

        return results
    finally:
        if restored:
            cleanup_error = remove_restored_playground(evaluation_input.restored_playground_name)
            if cleanup_error:
                logger.warning(
                    "Could not remove restored playground {}: {}",
                    evaluation_input.restored_playground_name,
                    cleanup_error,
                )


def store_evaluation(redis, evaluation_key: str, evaluation) -> str:
    redis.json().set(evaluation_key, "$", json.loads(evaluation.model_dump_json()))
    return evaluation_key


def evaluate_resolution_key(
    redis,
    resolution_key: str,
    analyses: list[str] | None = None,
) -> list[str]:
    resolution_data = redis.json().get(resolution_key)
    if not resolution_data:
        raise RuntimeError(f"No resolution found at {resolution_key}")

    selected_analyses = collect_analyses(analyses or ["core"])
    resolution = ConflictResolution.model_validate(resolution_data)
    evaluations = evaluate_resolution(resolution_key, resolution, selected_analyses)
    return [store_evaluation(redis, key, evaluation) for key, evaluation in evaluations]


def sync_evaluations(
    force: bool = False,
    analyses: list[str] | None = None,
) -> int:
    redis = setup_redis_connection()
    selected_analyses = collect_analyses(analyses or ["core"])
    resolution_keys = iter_resolution_keys(redis)
    synced = 0

    for resolution_key in resolution_keys:
        pending_analyses = [
            analysis for analysis in selected_analyses
            if force or not analysis_result_exists(redis, analysis.get_analysis_name(), resolution_key)
        ]
        if not pending_analyses:
            logger.info("Skipping already evaluated resolution {}", resolution_key)
            continue

        resolution_data = redis.json().get(resolution_key)
        if not resolution_data:
            logger.warning("Skipping missing resolution {}", resolution_key)
            continue

        resolution = ConflictResolution.model_validate(resolution_data)
        if resolution_has_error(resolution):
            logger.info("Skipping unsuccessful resolution {}", resolution_key)
            continue

        for evaluation_key, evaluation in evaluate_resolution(resolution_key, resolution, pending_analyses):
            store_evaluation(redis, evaluation_key, evaluation)
            evaluation_error = getattr(evaluation, "error", None)
            if evaluation_error:
                logger.error("Stored failed evaluation at {}: {}", evaluation_key, evaluation_error)
            else:
                logger.info("Stored evaluation at {}", evaluation_key)
            synced += 1

    logger.info("Evaluation sync complete: {} created", synced)
    return synced


def selected_analysis_names(args) -> list[str]:
    if args.all_analysis:
        return list(AVAILABLE_ANALYSES)
    if args.analysis:
        return args.analysis
    return ["core"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create evaluation records from saved conflict resolutions")
    parser.add_argument("--force", action="store_true", help="Overwrite existing evaluation records for selected analyses")
    parser.add_argument(
        "-a",
        "--analysis",
        action="append",
        help="Name of an analysis to run",
    )
    parser.add_argument(
        "--all-analysis",
        action="store_true",
        help="Run all available analyses",
    )
    parser.add_argument(
        "--list-analyses",
        action="store_true",
        help="List all available analyses and exit",
    )
    args = parser.parse_args()

    if args.list_analyses:
        for analysis in AVAILABLE_ANALYSES:
            print(analysis)
        return 0

    try:
        sync_evaluations(
            force=args.force,
            analyses=selected_analysis_names(args),
        )
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
