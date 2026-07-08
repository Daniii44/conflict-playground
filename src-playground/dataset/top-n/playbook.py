#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from common.redis_util import setup_redis_connection


DATASET_TOP_N_REPO_PREFIX = "dataset:top-n:repo:"


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def load_repos() -> list[dict[str, Any]]:
    redis = setup_redis_connection()
    repos = []

    for key in redis.scan_iter(match=f"{DATASET_TOP_N_REPO_PREFIX}*"):
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
    parser = argparse.ArgumentParser(description="Generate a top N repository playbook from Redis metadata")
    parser.add_argument("--count", type=positive_int, default=100, help="Number of repositories to include")
    parser.add_argument("--limit", type=positive_int, default=10, help="Conflict limit to write for each repository")
    parser.add_argument("--output", help="Output playbook filename, defaults to top<COUNT>raw.yaml")
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

    output_name = args.output or f"top{args.count}raw.yaml"
    output_path = Path(playbooks_dir) / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_playbook_yaml(selected_repos, args.limit), encoding="utf-8")

    logger.info(f"Wrote {len(selected_repos)} repositories to {output_path}")


if __name__ == "__main__":
    main()
