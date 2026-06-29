#!/usr/bin/env python3

import os
from collections import defaultdict
from functools import cache
from pathlib import Path

from common.git_util import capture_git
from common.repo_cache import repo_cache_key
from dataset.schesch.count import ScheschMergePair


def repo_cache_path(repo: str) -> Path:
    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    return caches / "repos" / repo_cache_key(repo)


@cache
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


def resolve_unique_merge_sha_from_parents(repo: str, parent_shas: tuple[str, str]) -> str:
    matches = merge_parent_index(repo).get(frozenset(parent_shas), [])

    if not matches:
        raise RuntimeError(
            f"No merge commit found in {repo} with parents {parent_shas[0]} and {parent_shas[1]}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"Found {len(matches)} merge commits in {repo} with parents "
            f"{parent_shas[0]} and {parent_shas[1]}"
        )

    return matches[0]
