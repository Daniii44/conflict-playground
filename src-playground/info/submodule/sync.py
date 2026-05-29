#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from redis import Redis

from common.git_util import capture_git
from common.playbook import load_playbook_data, load_playbook_repo_urls, resolve_playbook_path
from common.redis_util import INFO_SUBMODULE_PREFIX, setup_redis_connection
from common.repo_cache import repo_cache_key, resolve_submodule_url
from common.submodule import all_submodule_references, format_breadcrumbs
from info.conflict.list import list_conflicts


class SubmoduleSync:
    def __init__(self, cache_dir: Path, redis: Redis, *, head_only: bool = False):
        self.cache_dir = cache_dir
        self.redis = redis
        self.head_only = head_only
        self.synced_repos: set[str] = set()

    def sync_repo(self, url: str, breadcrumbs: tuple[str, ...] = ()) -> None:
        repo_key = repo_cache_key(url)
        if repo_key in self.synced_repos:
            logger.debug("[{}] Already recorded, skipping", format_breadcrumbs((*breadcrumbs, repo_key)))
            return
        self.synced_repos.add(repo_key)

        repo_path = self.cache_dir / repo_key
        current_breadcrumbs = (*breadcrumbs, repo_key)
        breadcrumb_label = format_breadcrumbs(current_breadcrumbs)

        if not self.is_available_repo(repo_path):
            logger.warning("[{}] Cached repo is unavailable: {}", breadcrumb_label, repo_path)
            self.record_node(
                repo_key,
                {
                    "repo": repo_key,
                    "url": url,
                    "unavailable": True,
                    "head_only": self.head_only,
                    "submodules": [],
                },
            )
            return

        submodules = []
        for reference in all_submodule_references(repo_path, current_breadcrumbs):
            if self.head_only and not reference.present_in_head:
                continue

            resolved_url = resolve_submodule_url(url, reference.url)
            child_key = repo_cache_key(resolved_url)
            child_path = self.cache_dir / child_key
            child_unavailable = not self.is_available_repo(child_path)

            logger.info(
                "[{}] Found submodule {}: {}",
                format_breadcrumbs((*current_breadcrumbs, child_key)),
                child_key,
                resolved_url,
            )
            submodules.append(
                {
                    "name": reference.name,
                    "path": reference.path,
                    "url": reference.url,
                    "resolved_url": resolved_url,
                    "repo": child_key,
                    "unavailable": child_unavailable,
                    "gitmodules_blob": reference.blob,
                    "present_in_head": reference.present_in_head,
                }
            )

        self.record_node(
            repo_key,
            {
                "repo": repo_key,
                "url": url,
                "unavailable": False,
                "head_only": self.head_only,
                "submodules": submodules,
            },
        )

        for submodule in submodules:
            self.sync_repo(submodule["resolved_url"], current_breadcrumbs)

    def is_available_repo(self, repo_path: Path) -> bool:
        if not repo_path.is_dir():
            return False

        result = capture_git(
            f"--git-dir={repo_path}",
            "rev-parse",
            "--git-dir",
            check=False,
        )
        return result.returncode == 0

    def record_node(self, repo_key: str, node: dict[str, Any]) -> None:
        self.redis.json().set(f"{INFO_SUBMODULE_PREFIX}{repo_key}", "$", node)


def origin_url(cache_dir: Path, repo_key: str) -> str | None:
    repo_path = cache_dir / repo_key
    if not repo_path.is_dir():
        return None

    result = capture_git(
        "-C",
        str(repo_path),
        "config",
        "--get",
        "remote.origin.url",
        check=False,
    )
    origin = result.stdout.strip()
    return origin or None


def load_root_repo_urls(playbook_path: Path, cache_dir: Path) -> list[str]:
    data = load_playbook_data(playbook_path)
    if data.get("playbook", {}).get("sources"):
        return load_playbook_repo_urls(playbook_path)

    conflict_types = data.get("playbook", {}).get("config", {}).get("conflict-types") or []
    repos = []
    seen = set()
    for repo, _merge_commit_oid in list_conflicts(conflict_types=conflict_types):
        if repo in seen:
            continue

        repos.append(origin_url(cache_dir, repo) or repo)
        seen.add(repo)

    return repos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record recursive submodule metadata for repositories referenced by a playbook"
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="default",
        help="Playbook name or path, defaults to default",
    )
    parser.add_argument(
        "--head",
        action="store_true",
        help="Only record submodule dependencies present in the latest commit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    playbooks_dir = Path(os.environ.get("PLAYBOOKS", str(Path.home() / "playbooks")))
    cache_dir = caches / "repos"

    playbook_path = resolve_playbook_path(args.playbook, playbooks_dir)
    if not playbook_path.is_file():
        logger.error("No such playbook: {}", playbook_path)
        return 1

    repo_urls = load_root_repo_urls(playbook_path, cache_dir)
    if not repo_urls:
        logger.error("No repositories found for playbook: {}", playbook_path)
        logger.error("Explicit playbooks need repo_url sources; dynamic playbooks need matching conflicts in Redis.")
        return 1

    sync = SubmoduleSync(cache_dir, setup_redis_connection(), head_only=args.head)
    for url in repo_urls:
        sync.sync_repo(url)

    logger.info("Done syncing submodule info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
