#!/usr/bin/env python3

import argparse
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.git_util import capture_git
from common.merge_tree import ConflictType, parse_merge_result, prune_auto_merged
from dataset.schesch.count import default_merge_analysis_path, iter_qualifying_merge_pairs
from dataset.schesch.merge_lookup import group_merge_pairs_by_repo, merge_parent_index, repo_cache_path


DEFAULT_LIMIT = 500
DEFAULT_SEED = 0


@dataclass(frozen=True, order=True)
class PlaybookCandidate:
    repo: str
    merge_sha: str


@dataclass(frozen=True)
class PlaybookBuildResult:
    playbook: dict
    unresolved_parent_pairs: int
    ambiguous_parent_pairs: int
    non_maven_merges: int
    no_content_conflict_merges: int
    non_content_conflict_merges: int
    sampled_out_merges: int
    skipped_repos: set[str]


def default_playbook_output_path() -> Path:
    playbooks_env = os.environ.get("PLAYBOOKS")
    if playbooks_env:
        return Path(playbooks_env) / "schesch.yaml"

    local_playbooks = Path.cwd() / "data" / "playbooks"
    if local_playbooks.exists():
        return local_playbooks / "schesch.yaml"

    return Path("/root/playbooks/schesch.yaml")


def has_top_level_pom(repo: str, merge_sha: str) -> bool:
    result = capture_git(
        f"--git-dir={repo_cache_path(repo)}",
        "cat-file",
        "-e",
        f"{merge_sha}^{{tree}}:pom.xml",
        check=False,
    )
    return result.returncode == 0


def merge_conflict_types(repo: str, left_parent: str, right_parent: str) -> tuple[ConflictType, ...]:
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
    return tuple(conflict.type for conflict in merge_result.logical_conflicts)


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


def build_schesch_playbook_result(
    merge_analysis: Path,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
) -> PlaybookBuildResult:
    merges_by_repo = group_merge_pairs_by_repo(list(iter_qualifying_merge_pairs(merge_analysis)))
    unresolved_parent_pairs = 0
    ambiguous_parent_pairs = 0
    non_maven_merges = 0
    no_content_conflict_merges = 0
    non_content_conflict_merges = 0
    skipped_repos: set[str] = set()
    candidates: list[PlaybookCandidate] = []

    for repo in sorted(merges_by_repo):
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
                conflict_types = merge_conflict_types(repo, left_parent, right_parent)
            except Exception as error:
                logger.warning(
                    "{}: pruning merge {} because merge-tree conflict parsing failed: {}",
                    repo,
                    merge_sha,
                    error,
                )
                no_content_conflict_merges += 1
                continue

            if not conflict_types:
                no_content_conflict_merges += 1
                continue

            if any(conflict_type != ConflictType.CONFLICT_CONTENTS for conflict_type in conflict_types):
                non_content_conflict_merges += 1
                continue

            candidates.append(PlaybookCandidate(repo=repo, merge_sha=merge_sha))

    selected_candidates = select_random_candidates(candidates, limit=limit, seed=seed)

    return PlaybookBuildResult(
        playbook=build_playbook_from_candidates(selected_candidates),
        unresolved_parent_pairs=unresolved_parent_pairs,
        ambiguous_parent_pairs=ambiguous_parent_pairs,
        non_maven_merges=non_maven_merges,
        no_content_conflict_merges=no_content_conflict_merges,
        non_content_conflict_merges=non_content_conflict_merges,
        sampled_out_merges=len(candidates) - len(selected_candidates),
        skipped_repos=skipped_repos,
    )


def build_schesch_playbook(
    merge_analysis: Path,
    *,
    limit: int | None = DEFAULT_LIMIT,
    seed: int = DEFAULT_SEED,
) -> dict:
    return build_schesch_playbook_result(merge_analysis, limit=limit, seed=seed).playbook


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
        help="Output playbook path.",
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
    result = build_schesch_playbook_result(args.merge_analysis, limit=limit, seed=args.seed)
    playbook = result.playbook
    sources = playbook["playbook"]["sources"]
    merge_count = sum(len(source["override_merge_shas"]) for source in sources)

    write_playbook(playbook, args.output)
    logger.info(
        "Wrote Schesch playbook with {} repositories and {} merge overrides to {}",
        len(sources),
        merge_count,
        args.output,
    )
    if result.unresolved_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that could not be resolved to a merge commit",
            result.unresolved_parent_pairs,
        )
    if result.ambiguous_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that resolved to multiple merge commits",
            result.ambiguous_parent_pairs,
        )
    if result.non_maven_merges:
        logger.warning("Pruned {} merges without a top-level pom.xml", result.non_maven_merges)
    if result.no_content_conflict_merges:
        logger.warning(
            "Pruned {} merges that did not produce content conflicts",
            result.no_content_conflict_merges,
        )
    if result.non_content_conflict_merges:
        logger.warning(
            "Pruned {} merges containing at least one non-contents conflict",
            result.non_content_conflict_merges,
        )
    if result.sampled_out_merges:
        logger.info("Random sampling pruned {} otherwise eligible merges", result.sampled_out_merges)
    if result.skipped_repos:
        logger.error(
            "Skipped {} repositories because their cached bare repository was missing or inaccessible",
            len(result.skipped_repos),
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
