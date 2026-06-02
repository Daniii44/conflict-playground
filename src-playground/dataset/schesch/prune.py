#!/usr/bin/env python3

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.git_util import capture_git
from common.repo_cache import repo_cache_key
from common.redis_util import setup_redis_connection
from dataset.schesch.count import (
    ScheschMergePair,
    default_merge_analysis_path,
    iter_qualifying_merge_pairs,
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


def parse_conflict_key(key: str) -> ConflictKey | None:
    parts = key.split(":", 4)
    if len(parts) != 5 or parts[0] != "info" or parts[1] != "conflict":
        return None

    _, _, analysis, repo, merge_sha = parts
    if not analysis or not repo or not merge_sha:
        return None

    return ConflictKey(key=key, analysis=analysis, repo=repo, merge_sha=merge_sha)


def repo_cache_path(repo: str) -> Path:
    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    return caches / "repos" / repo_cache_key(repo)


def merge_parent_index(repo: str) -> dict[frozenset[str], list[str]]:
    bare_repo = repo_cache_path(repo)
    if not bare_repo.is_dir():
        raise RuntimeError(f"Bare repository does not exist: {bare_repo}")

    result = capture_git(
        f"--git-dir={bare_repo}",
        "rev-list",
        "--all",
        "--merges",
        "--parents",
    )

    index: dict[frozenset[str], list[str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue

        merge_sha, first_parent, second_parent = parts
        index.setdefault(frozenset((first_parent, second_parent)), []).append(merge_sha)

    return index


def group_merge_pairs_by_repo(merge_pairs: list[ScheschMergePair]) -> dict[str, set[tuple[str, str]]]:
    grouped: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for merge_pair in merge_pairs:
        grouped[repo_cache_key(merge_pair.repo)].add((merge_pair.left_parent, merge_pair.right_parent))
    return grouped


def resolve_allowed_merge_shas(
    merge_pairs: list[ScheschMergePair],
) -> tuple[dict[str, set[str]], set[str]]:
    allowed_by_repo: dict[str, set[str]] = {}
    skipped_repos: set[str] = set()

    for repo, parent_pairs in group_merge_pairs_by_repo(merge_pairs).items():
        try:
            index = merge_parent_index(repo)
        except RuntimeError as error:
            logger.error("Skipping {}: {}", repo, error)
            skipped_repos.add(repo)
            continue

        allowed_shas: set[str] = set()
        repo_failed = False
        for left_parent, right_parent in parent_pairs:
            matches = index.get(frozenset((left_parent, right_parent)), [])
            if not matches:
                logger.error(
                    "Skipping {}: no merge commit found for parents {} and {}",
                    repo,
                    left_parent,
                    right_parent,
                )
                repo_failed = True
                continue

            if len(matches) > 1:
                logger.warning(
                    "{} has {} merge commits for parents {} and {}; keeping all matches",
                    repo,
                    len(matches),
                    left_parent,
                    right_parent,
                )

            allowed_shas.update(matches)

        if repo_failed:
            skipped_repos.add(repo)
            continue

        allowed_by_repo[repo] = allowed_shas

    return allowed_by_repo, skipped_repos


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

    allowed_by_repo, skipped_repos = resolve_allowed_merge_shas(merge_pairs)
    logger.info(
        "Resolved {} allowed merge commits across {} repositories",
        sum(len(shas) for shas in allowed_by_repo.values()),
        len(allowed_by_repo),
    )

    redis = setup_redis_connection()
    result = prune_conflict_keys(redis, allowed_by_repo, dry_run=args.dry_run)
    action = "Would delete" if args.dry_run else "Deleted"
    print(
        f"{action} {result.deleted} info:conflict entries "
        f"({result.kept} kept, {result.scanned} scanned, {result.skipped} skipped)"
    )

    if skipped_repos:
        logger.error(
            "Skipped pruning {} repositories because their allowed merge set was incomplete",
            len(skipped_repos),
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
