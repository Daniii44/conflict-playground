#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from pathlib import Path

from loguru import logger
from common.git_util import capture_git, stream_git
from common.playbook import load_playbook_repo_urls, resolve_playbook_path
from common.repo_cache import repo_cache_key, resolve_submodule_url
from common.submodule import format_breadcrumbs, gitmodules_blobs, submodule_urls


class RepoSync:
    def __init__(self, cache_dir: Path, *, sync_submodules: bool = True):
        self.cache_dir = cache_dir
        self.sync_submodules_enabled = sync_submodules
        self.synced_repos: set[Path] = set()

    def sync_repo(self, url: str, *, required: bool, breadcrumbs: tuple[str, ...]) -> None:
        repo_key = repo_cache_key(url)
        target_path = self.cache_dir / repo_key
        current_breadcrumbs = (*breadcrumbs, repo_key)
        breadcrumb_label = format_breadcrumbs(current_breadcrumbs)

        if target_path in self.synced_repos:
            logger.debug("[{}] Already synced, skipping", breadcrumb_label)
            return
        self.synced_repos.add(target_path)

        if target_path.is_dir():
            existing_origin = capture_git(
                "-C",
                str(target_path),
                "config",
                "--get",
                "remote.origin.url",
                check=False,
            ).stdout.strip()

            if existing_origin and existing_origin != url:
                logger.warning(
                    "[{}] Cache path already points at {}, not {}",
                    breadcrumb_label,
                    existing_origin,
                    url,
                )

            logger.info("[{}] Syncing existing repo", breadcrumb_label)
            result = stream_git("-C", str(target_path), "fetch", "--all", "--prune")
        else:
            logger.info("[{}] Loading new repo: {}", breadcrumb_label, url)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            result = stream_git("clone", "--bare", url, str(target_path))

        if result.returncode != 0:
            if required:
                raise subprocess.CalledProcessError(result.returncode, result.args)

            logger.warning("[{}] Failed to sync submodule repo: {}", breadcrumb_label, url)
            return

        if self.sync_submodules_enabled:
            self.sync_submodules(target_path, url, current_breadcrumbs)
        else:
            logger.info("[{}] Skipping submodule sync", breadcrumb_label)

    def sync_submodules(
        self,
        repo_path: Path,
        repo_url: str,
        breadcrumbs: tuple[str, ...],
    ) -> None:
        for blob in gitmodules_blobs(repo_path, breadcrumbs):
            for submodule_url in submodule_urls(repo_path, blob, breadcrumbs):
                resolved_url = resolve_submodule_url(repo_url, submodule_url)
                submodule_key = repo_cache_key(resolved_url)
                logger.info(
                    "[{}] Found submodule {}: {}",
                    format_breadcrumbs((*breadcrumbs, submodule_key)),
                    submodule_key,
                    resolved_url,
                )
                self.sync_repo(resolved_url, required=False, breadcrumbs=breadcrumbs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync repositories referenced by a playbook")
    parser.add_argument(
        "playbook",
        nargs="?",
        default="default",
        help="Playbook name or path, defaults to default",
    )
    parser.add_argument(
        "--no-submodules",
        action="store_true",
        help="Do not recursively cache submodule repositories.",
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

    repo_urls = load_playbook_repo_urls(playbook_path)
    if not repo_urls:
        logger.error("No explicit repositories found in playbook: {}", playbook_path)
        logger.error(
            "Dynamic playbooks cannot be repository-synced before Redis contains matching conflicts."
        )
        return 1

    cache_dir.mkdir(parents=True, exist_ok=True)

    sync = RepoSync(cache_dir, sync_submodules=not args.no_submodules)
    failed_repo_urls = []
    for url in repo_urls:
        try:
            sync.sync_repo(url, required=True, breadcrumbs=())
        except subprocess.CalledProcessError as error:
            failed_repo_urls.append(url)
            logger.error("Failed to sync required repo {} with command: {}", url, " ".join(error.cmd))

    if failed_repo_urls:
        logger.error(
            "Done syncing repository cache with {} failed required repos",
            len(failed_repo_urls),
        )
        for url in failed_repo_urls:
            logger.error("Failed required repo: {}", url)
        return 1

    logger.info("Done syncing repository cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
