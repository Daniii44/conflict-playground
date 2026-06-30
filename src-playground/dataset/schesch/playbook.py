#!/usr/bin/env python3

import argparse
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.git_util import capture_git
from common.merge_tree import ConflictType, MergeLogicalConflict, parse_merge_result, prune_auto_merged
from common.redis_util import setup_redis_connection
from dataset.schesch.count import default_merge_analysis_path, iter_qualifying_merge_pairs
from dataset.schesch.merge_lookup import group_merge_pairs_by_repo, merge_parent_index, repo_cache_path


DEFAULT_LIMIT = 500
DEFAULT_SEED = 0
CONTENT_CONFLICT_INFO_PREFIX = "CONFLICT (content)"


@dataclass(frozen=True, order=True)
class PlaybookCandidate:
    repo: str
    merge_sha: str


@dataclass(frozen=True)
class RawPlaybookBuildResult:
    playbook: dict
    candidates: list[PlaybookCandidate]
    unresolved_parent_pairs: int
    ambiguous_parent_pairs: int
    non_maven_merges: int
    no_content_conflict_merges: int
    non_content_conflict_merges: int
    sampled_out_merges: int
    skipped_repos: set[str]


@dataclass(frozen=True)
class PlaybookBuildResult:
    playbook: dict
    candidates: list[PlaybookCandidate]
    raw_result: RawPlaybookBuildResult
    missing_schesch_info_merges: int
    failed_schesch_info_merges: int
    inconsistent_schesch_environment_merges: int
    sampled_out_merges: int


def default_playbook_output_path() -> Path:
    playbooks_env = os.environ.get("PLAYBOOKS")
    if playbooks_env:
        return Path(playbooks_env) / "schesch.yaml"

    local_playbooks = Path.cwd() / "data" / "playbooks"
    if local_playbooks.exists():
        return local_playbooks / "schesch.yaml"

    return Path("/root/playbooks/schesch.yaml")


def default_raw_playbook_output_path() -> Path:
    final_output = default_playbook_output_path()
    return final_output.with_name("schesch-raw.yaml")


def has_top_level_pom(repo: str, merge_sha: str) -> bool:
    result = capture_git(
        f"--git-dir={repo_cache_path(repo)}",
        "cat-file",
        "-e",
        f"{merge_sha}^{{tree}}:pom.xml",
        check=False,
    )
    return result.returncode == 0


def merge_logical_conflicts(repo: str, left_parent: str, right_parent: str) -> tuple[MergeLogicalConflict, ...]:
    result = capture_git(
        f"--git-dir={repo_cache_path(repo)}",
        "merge-tree",
        "-z",
        left_parent,
        right_parent,
        check=False,
    )
    output = result.stdout.encode()
    stderr = result.stderr.encode()
    if result.returncode == 0 or b"fatal: refusing to merge unrelated histories" in output + stderr:
        return tuple()

    merge_result = prune_auto_merged(parse_merge_result(output))
    return tuple(merge_result.logical_conflicts)


def is_content_conflict(conflict: MergeLogicalConflict) -> bool:
    return (
        conflict.type == ConflictType.CONFLICT_CONTENTS
        and conflict.info.startswith(CONTENT_CONFLICT_INFO_PREFIX)
    )


def repo_is_cached(repo: str) -> bool:
    return repo_cache_path(repo).is_dir()


def schesch_info_key(candidate: PlaybookCandidate) -> str:
    return f"info:conflict:schesch:{candidate.repo}:{candidate.merge_sha}"


def passed_schesch_resolution(result: dict | None) -> bool:
    return bool(result and result.get("passed"))


def schesch_results_use_same_environment(results: list[dict]) -> bool:
    build_tools = {result.get("build_tool") for result in results}
    java_homes = {result.get("successful_java_home") for result in results}
    return (
        len(build_tools) == 1
        and None not in build_tools
        and len(java_homes) == 1
        and None not in java_homes
    )


def schesch_info_allows_candidate(info: dict) -> tuple[bool, bool]:
    human = info.get("human")
    parents = info.get("parents") or []
    results = [human, *parents]
    if human is None or len(parents) != 2:
        return False, False
    if not all(passed_schesch_resolution(result) for result in results):
        return False, False
    if not schesch_results_use_same_environment(results):
        return False, True
    return True, False


def select_random_candidates(
    candidates: list[PlaybookCandidate],
    *,
    limit: int | None,
    seed: int,
) -> list[PlaybookCandidate]:
    if limit is None or len(candidates) <= limit:
        return sorted(candidates)

    return sorted(random.Random(seed).sample(candidates, limit))


def build_playbook_from_candidates(candidates: list[PlaybookCandidate]) -> dict:
    sources = []
    current_repo = None
    current_merge_shas: list[str] = []

    for candidate in sorted(candidates):
        if candidate.repo != current_repo:
            if current_repo is not None:
                sources.append(
                    {
                        "repo_url": f"https://github.com/{current_repo}",
                        "override_merge_shas": current_merge_shas,
                    }
                )
            current_repo = candidate.repo
            current_merge_shas = []

        current_merge_shas.append(candidate.merge_sha)

    if current_repo is not None:
        sources.append(
            {
                "repo_url": f"https://github.com/{current_repo}",
                "override_merge_shas": current_merge_shas,
            }
        )

    return {"playbook": {"sources": sources}}


def build_schesch_raw_playbook_result(
    merge_analysis: Path,
) -> RawPlaybookBuildResult:
    merges_by_repo = group_merge_pairs_by_repo(list(iter_qualifying_merge_pairs(merge_analysis)))
    unresolved_parent_pairs = 0
    ambiguous_parent_pairs = 0
    non_maven_merges = 0
    no_content_conflict_merges = 0
    non_content_conflict_merges = 0
    skipped_repos: set[str] = set()
    candidates: list[PlaybookCandidate] = []

    for repo in sorted(merges_by_repo):
        if not repo_is_cached(repo):
            logger.warning("Skipping {}: cached bare repository does not exist", repo)
            skipped_repos.add(repo)
            continue

        try:
            index = merge_parent_index(repo)
        except RuntimeError as error:
            logger.error("Skipping {}: {}", repo, error)
            skipped_repos.add(repo)
            continue

        for left_parent, right_parent in sorted(merges_by_repo[repo]):
            matches = index.get(frozenset((left_parent, right_parent)), [])
            if not matches:
                logger.warning(
                    "{}: no merge commit found for parents {} and {}",
                    repo,
                    left_parent,
                    right_parent,
                )
                unresolved_parent_pairs += 1
                continue

            if len(matches) > 1:
                logger.warning(
                    "{}: pruning parent pair {} and {} because it resolves to {} merge commits",
                    repo,
                    left_parent,
                    right_parent,
                    len(matches),
                )
                ambiguous_parent_pairs += 1
                continue

            merge_sha = matches[0]
            if not has_top_level_pom(repo, merge_sha):
                non_maven_merges += 1
                continue

            try:
                logical_conflicts = merge_logical_conflicts(repo, left_parent, right_parent)
            except Exception as error:
                logger.warning(
                    "{}: pruning merge {} because merge-tree conflict parsing failed: {}",
                    repo,
                    merge_sha,
                    error,
                )
                no_content_conflict_merges += 1
                continue

            if not logical_conflicts:
                no_content_conflict_merges += 1
                continue

            if any(not is_content_conflict(conflict) for conflict in logical_conflicts):
                non_content_conflict_merges += 1
                continue

            candidates.append(PlaybookCandidate(repo=repo, merge_sha=merge_sha))

    return RawPlaybookBuildResult(
        playbook=build_playbook_from_candidates(candidates),
        candidates=sorted(candidates),
        unresolved_parent_pairs=unresolved_parent_pairs,
        ambiguous_parent_pairs=ambiguous_parent_pairs,
        non_maven_merges=non_maven_merges,
        no_content_conflict_merges=no_content_conflict_merges,
        non_content_conflict_merges=non_content_conflict_merges,
        sampled_out_merges=0,
        skipped_repos=skipped_repos,
    )


def filter_schesch_candidates(
    candidates: list[PlaybookCandidate],
    redis,
) -> tuple[list[PlaybookCandidate], int, int, int]:
    selected: list[PlaybookCandidate] = []
    missing_info = 0
    failed_info = 0
    inconsistent_environment = 0

    for candidate in sorted(candidates):
        data = redis.json().get(schesch_info_key(candidate))
        if not data:
            missing_info += 1
            logger.error("{} is missing", schesch_info_key(candidate))
            continue

        allowed, environment_mismatch = schesch_info_allows_candidate(data)
        if allowed:
            selected.append(candidate)
        elif environment_mismatch:
            inconsistent_environment += 1
        else:
            failed_info += 1

    return selected, missing_info, failed_info, inconsistent_environment


def build_schesch_playbook_result(
    raw_result: RawPlaybookBuildResult,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
    redis=None,
) -> PlaybookBuildResult:
    redis = redis or setup_redis_connection()
    filtered_candidates, missing_info, failed_info, inconsistent_environment = filter_schesch_candidates(
        raw_result.candidates,
        redis,
    )
    selected_candidates = select_random_candidates(filtered_candidates, limit=limit, seed=seed)

    return PlaybookBuildResult(
        playbook=build_playbook_from_candidates(selected_candidates),
        candidates=selected_candidates,
        raw_result=raw_result,
        missing_schesch_info_merges=missing_info,
        failed_schesch_info_merges=failed_info,
        inconsistent_schesch_environment_merges=inconsistent_environment,
        sampled_out_merges=len(filtered_candidates) - len(selected_candidates),
    )


def build_schesch_playbook_result_from_merge_analysis(
    merge_analysis: Path,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
    redis=None,
) -> PlaybookBuildResult:
    return build_schesch_playbook_result(
        build_schesch_raw_playbook_result(merge_analysis),
        limit=limit,
        seed=seed,
        redis=redis or setup_redis_connection(),
    )


def build_schesch_raw_playbook(
    merge_analysis: Path,
) -> dict:
    return build_schesch_raw_playbook_result(merge_analysis).playbook


def build_schesch_playbook(
    merge_analysis: Path,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
    redis=None,
) -> dict:
    result = build_schesch_playbook_result_from_merge_analysis(
        merge_analysis,
        limit=limit,
        seed=seed,
        redis=redis,
    )
    if result.missing_schesch_info_merges:
        raise RuntimeError(
            f"Missing info:conflict:schesch data for {result.missing_schesch_info_merges} raw candidates"
        )
    return result.playbook


def generate_schesch_playbooks(
    merge_analysis: Path,
    raw_output: Path,
    output: Path,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
    redis=None,
) -> tuple[RawPlaybookBuildResult, PlaybookBuildResult | None]:
    raw_result = build_schesch_raw_playbook_result(merge_analysis)
    write_playbook(raw_result.playbook, raw_output)

    if raw_result.skipped_repos:
        return raw_result, None

    result = build_schesch_playbook_result(
        raw_result,
        limit=limit,
        seed=seed,
        redis=redis or setup_redis_connection(),
    )
    if result.missing_schesch_info_merges:
        return raw_result, result

    write_playbook(result.playbook, output)
    return raw_result, result


def write_playbook(playbook: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("playbook:\n")
        handle.write("  sources:\n")
        for source in playbook["playbook"]["sources"]:
            handle.write(f"    - repo_url: {source['repo_url']}\n")
            handle.write("      override_merge_shas:\n")
            for merge_sha in source["override_merge_shas"]:
                handle.write(f"        - {merge_sha}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a playbook for the retained Schesch merge_analysis subset. "
            "Merge commits are resolved from parent pairs using cached bare repositories."
        )
    )
    parser.add_argument(
        "--merge-analysis",
        type=Path,
        default=default_merge_analysis_path(),
        help="Path to data/datasets/schesch/merge_analysis.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_playbook_output_path(),
        help="Output filtered playbook path.",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=default_raw_playbook_output_path(),
        help="Output raw playbook path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum number of randomly selected conflicts to write. Use 0 to write all remaining conflicts.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed used when --limit selects a subset.",
    )
    args = parser.parse_args()

    if not args.merge_analysis.is_dir():
        parser.error(f"merge_analysis directory does not exist: {args.merge_analysis}")
    if args.limit < 0:
        parser.error("--limit must be non-negative")

    limit = None if args.limit == 0 else args.limit
    raw_result, result = generate_schesch_playbooks(
        args.merge_analysis,
        args.raw_output,
        args.output,
        limit=limit,
        seed=args.seed,
    )
    raw_sources = raw_result.playbook["playbook"]["sources"]
    raw_merge_count = sum(len(source["override_merge_shas"]) for source in raw_sources)

    logger.info(
        "Wrote raw Schesch playbook with {} repositories and {} merge overrides to {}",
        len(raw_sources),
        raw_merge_count,
        args.raw_output,
    )

    if raw_result.unresolved_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that could not be resolved to a merge commit",
            raw_result.unresolved_parent_pairs,
        )
    if raw_result.ambiguous_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that resolved to multiple merge commits",
            raw_result.ambiguous_parent_pairs,
        )
    if raw_result.non_maven_merges:
        logger.warning("Pruned {} merges without a top-level pom.xml", raw_result.non_maven_merges)
    if raw_result.no_content_conflict_merges:
        logger.warning(
            "Pruned {} merges that did not produce content conflicts",
            raw_result.no_content_conflict_merges,
        )
    if raw_result.non_content_conflict_merges:
        logger.warning(
            "Pruned {} merges containing at least one non-contents conflict",
            raw_result.non_content_conflict_merges,
        )
    if raw_result.skipped_repos:
        logger.error(
            "Skipped {} repositories because their cached bare repository was missing or inaccessible",
            len(raw_result.skipped_repos),
        )
        return 1

    if result is None:
        return 1

    if result.missing_schesch_info_merges:
        logger.error(
            "Refusing to write {} because {} raw candidates are missing info:conflict:schesch records",
            args.output,
            result.missing_schesch_info_merges,
        )
        return 1

    sources = result.playbook["playbook"]["sources"]
    merge_count = sum(len(source["override_merge_shas"]) for source in sources)

    logger.info(
        "Wrote filtered Schesch playbook with {} repositories and {} merge overrides to {}",
        len(sources),
        merge_count,
        args.output,
    )
    if result.failed_schesch_info_merges:
        logger.warning(
            "Pruned {} raw candidates because the human resolution or a parent did not pass",
            result.failed_schesch_info_merges,
        )
    if result.inconsistent_schesch_environment_merges:
        logger.warning(
            "Pruned {} raw candidates because human and parent checks did not use the same build tool and Java home",
            result.inconsistent_schesch_environment_merges,
        )
    if result.sampled_out_merges:
        logger.info("Random sampling pruned {} otherwise eligible Schesch-passing merges", result.sampled_out_merges)

    return 0


if __name__ == "__main__":
    sys.exit(main())
