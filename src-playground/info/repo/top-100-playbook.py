#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from common.redis_util import setup_redis_connection


INFO_REPO_PREFIX = "info:repo:"


def load_repos() -> list[dict[str, Any]]:
    redis = setup_redis_connection()
    repos = []

    for key in redis.scan_iter(match=f"{INFO_REPO_PREFIX}*"):
        repo = redis.json().get(key)
        if not repo:
            logger.warning(f"Skipping empty repo metadata at {key}")
            continue
        if not repo.get("clone_url"):
            logger.warning(f"Skipping repo metadata without clone_url at {key}")
            continue
        repos.append(repo)

    return repos


def build_playbook_yaml(repos: list[dict[str, Any]], per_repo_limit: int) -> str:
    lines = [
        "playbook:",
        "  sources:",
    ]

    for repo in repos:
        lines.extend([
            f"    - repo_url: {repo['clone_url']}",
            f"      limit: {per_repo_limit}",
        ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate top-100.yaml from stored repo metadata in Redis")
    parser.add_argument("--count", type=int, default=100, help="Number of repositories to include")
    parser.add_argument("--limit", type=int, default=10, help="Conflict limit to write for each repository")
    parser.add_argument("--output", default="top-100.yaml", help="Output playbook filename")
    args = parser.parse_args()

    playbooks_dir = os.environ.get("PLAYBOOKS")
    if not playbooks_dir:
        logger.error("PLAYBOOKS environment variable is not set")
        sys.exit(1)

    repos = load_repos()
    repos.sort(key=lambda repo: repo.get("star_count") or 0, reverse=True)
    selected_repos = repos[:args.count]

    if len(selected_repos) < args.count:
        logger.warning(f"Only found {len(selected_repos)} repositories in Redis")

    output_path = Path(playbooks_dir) / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_playbook_yaml(selected_repos, args.limit), encoding="utf-8")

    logger.info(f"Wrote {len(selected_repos)} repositories to {output_path}")


if __name__ == "__main__":
    main()
