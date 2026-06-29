#!/usr/bin/env python3

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.redis_util import setup_redis_connection
from dataset.schesch.count import (
    ScheschMergePair,
    default_merge_analysis_path,
    iter_qualifying_merge_pairs,
)
from dataset.schesch.merge_lookup import (
    group_merge_pairs_by_repo,
    merge_parent_index,
    repo_cache_path,
)


@dataclass(frozen=True)
class ConflictKey:
    key: str
    analysis: str
    repo: str
    merge_sha: str


@dataclass(frozen=True)
class PruneResult:
    scanned: int
    deleted: int
    kept: int
    skipped: int


@dataclass(frozen=True)
class ResolveResult:
    allowed_by_repo: dict[str, set[str]]
    skipped_repos: set[str]
    unresolved_parent_pairs: int
    repos_with_unresolved_parent_pairs: int
    ambiguous_parent_pairs: int
    repos_with_ambiguous_parent_pairs: int


def parse_conflict_key(key: str) -> ConflictKey | None:
    parts = key.split(":", 4)
    if len(parts) != 5 or parts[0] != "info" or parts[1] != "conflict":
        return None

    _, _, analysis, repo, merge_sha = parts
    if not analysis or not repo or not merge_sha:
        return None

    return ConflictKey(key=key, analysis=analysis, repo=repo, merge_sha=merge_sha)


def resolve_allowed_merge_shas(
    merge_pairs: list[ScheschMergePair],
) -> ResolveResult:
    allowed_by_repo: dict[str, set[str]] = {}
    skipped_repos: set[str] = set()
    unresolved_parent_pairs = 0
    repos_with_unresolved_parent_pairs: set[str] = set()
    ambiguous_parent_pairs = 0
    repos_with_ambiguous_parent_pairs: set[str] = set()

    for repo, parent_pairs in group_merge_pairs_by_repo(merge_pairs).items():
        try:
            index = merge_parent_index(repo)
        except RuntimeError as error:
            logger.error("Skipping {}: {}", repo, error)
            skipped_repos.add(repo)
            continue

        allowed_shas: set[str] = set()
        for left_parent, right_parent in parent_pairs:
            matches = index.get(frozenset((left_parent, right_parent)), [])
            if not matches:
                logger.warning(
                    "{}: no merge commit found for parents {} and {}",
                    repo,
                    left_parent,
                    right_parent,
                )
                unresolved_parent_pairs += 1
                repos_with_unresolved_parent_pairs.add(repo)
                continue

            if len(matches) > 1:
                logger.warning(
                    "{} has {} merge commits for parents {} and {}; pruning parent pair",
                    repo,
                    len(matches),
                    left_parent,
                    right_parent,
                )
                ambiguous_parent_pairs += 1
                repos_with_ambiguous_parent_pairs.add(repo)
                continue

            allowed_shas.update(matches)

        allowed_by_repo[repo] = allowed_shas

    return ResolveResult(
        allowed_by_repo=allowed_by_repo,
        skipped_repos=skipped_repos,
        unresolved_parent_pairs=unresolved_parent_pairs,
        repos_with_unresolved_parent_pairs=len(repos_with_unresolved_parent_pairs),
        ambiguous_parent_pairs=ambiguous_parent_pairs,
        repos_with_ambiguous_parent_pairs=len(repos_with_ambiguous_parent_pairs),
    )


def prune_conflict_keys(redis, allowed_by_repo: dict[str, set[str]], *, dry_run: bool) -> PruneResult:
    scanned = 0
    deleted = 0
    kept = 0
    skipped = 0

    for key in redis.scan_iter(match="info:conflict:*"):
        conflict_key = parse_conflict_key(key)
        if conflict_key is None:
            skipped += 1
            continue

        allowed_shas = allowed_by_repo.get(conflict_key.repo)
        if allowed_shas is None:
            skipped += 1
            continue

        scanned += 1
        if conflict_key.merge_sha in allowed_shas:
            kept += 1
            continue

        deleted += 1
        if not dry_run:
            redis.delete(conflict_key.key)

    return PruneResult(scanned=scanned, deleted=deleted, kept=kept, skipped=skipped)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prune info:conflict:* Redis entries for the retained Schesch dataset "
            "to only the merge commits represented by merge_analysis parent pairs."
        )
    )
    parser.add_argument(
        "--merge-analysis",
        type=Path,
        default=default_merge_analysis_path(),
        help="Path to data/datasets/schesch/merge_analysis.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting Redis keys.",
    )
    args = parser.parse_args()

    if not args.merge_analysis.is_dir():
        parser.error(f"merge_analysis directory does not exist: {args.merge_analysis}")

    merge_pairs = list(iter_qualifying_merge_pairs(args.merge_analysis))
    logger.info("Loaded {} retained Schesch parent pairs", len(merge_pairs))

    resolve_result = resolve_allowed_merge_shas(merge_pairs)
    logger.info(
        "Resolved {} allowed merge commits across {} repositories",
        sum(len(shas) for shas in resolve_result.allowed_by_repo.values()),
        len(resolve_result.allowed_by_repo),
    )
    if resolve_result.unresolved_parent_pairs:
        logger.warning(
            "{} retained parent pairs across {} repositories could not be resolved to merge commits",
            resolve_result.unresolved_parent_pairs,
            resolve_result.repos_with_unresolved_parent_pairs,
        )
    if resolve_result.ambiguous_parent_pairs:
        logger.warning(
            "{} retained parent pairs across {} repositories resolved to multiple merge commits and were pruned",
            resolve_result.ambiguous_parent_pairs,
            resolve_result.repos_with_ambiguous_parent_pairs,
        )

    redis = setup_redis_connection()
    result = prune_conflict_keys(redis, resolve_result.allowed_by_repo, dry_run=args.dry_run)
    action = "Would delete" if args.dry_run else "Deleted"
    print(
        f"{action} {result.deleted} info:conflict entries "
        f"({result.kept} kept, {result.scanned} scanned, {result.skipped} skipped)"
    )

    if resolve_result.skipped_repos:
        logger.error(
            "Skipped pruning {} repositories because their cached bare repository was missing or inaccessible",
            len(resolve_result.skipped_repos),
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
