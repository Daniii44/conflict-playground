#!/usr/bin/env python3

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from common.playbook import resolve_playbook_path
from common.redis_util import INFO_SUBMODULE_PREFIX, setup_redis_connection
from common.repo_cache import repo_cache_key
from info.submodule.sync import load_root_repo_urls


DEFAULT_OUTPUT = "submoduleraw.yaml"
DEFAULT_LIMIT = 100
SUBMODULE_CONFLICT_TYPE_PERCENTAGES = {
    "CONFLICT (submodule with possible resolution)": 40,
    "CONFLICT (submodule may have rewinds)": 40,
    "CONFLICT (submodule)": 20,
}


@dataclass(frozen=True)
class SubmodulePlaybookSource:
    repo: str
    repo_url: str
    available_submodule_count: int


def load_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def load_submodule_node(redis, repo: str) -> dict[str, Any] | None:
    value = redis.json().get(f"{INFO_SUBMODULE_PREFIX}{repo}")
    if value is None:
        return None

    node = load_json_value(value)
    if not isinstance(node, dict):
        logger.warning("Skipping malformed submodule info for {}", repo)
        return None

    return node


def node_is_available(node: dict[str, Any] | None) -> bool:
    return bool(node) and not node.get("unavailable", False)


def source_url(repo: str, node: dict[str, Any]) -> str:
    url = node.get("url")
    if isinstance(url, str) and url:
        return url

    return f"https://github.com/{repo}"


def available_submodule_repos(
    redis,
    node: dict[str, Any],
    *,
    head_only: bool = False,
) -> list[str]:
    repos = []
    seen = set()
    for submodule in node.get("submodules", []):
        if not isinstance(submodule, dict):
            continue
        if head_only and not submodule.get("present_in_head", False):
            continue
        if submodule.get("unavailable", False):
            continue

        repo = submodule.get("repo")
        if not isinstance(repo, str) or not repo or repo in seen:
            continue

        child_node = load_submodule_node(redis, repo)
        if not node_is_available(child_node):
            logger.warning("Skipping unavailable or missing submodule info for {}", repo)
            continue

        repos.append(repo)
        seen.add(repo)

    return repos


def collect_submodule_playbook_sources(
    redis,
    root_repos: list[str],
    *,
    head_only: bool = False,
) -> list[SubmodulePlaybookSource]:
    selected: dict[str, SubmodulePlaybookSource] = {}
    visited: set[str] = set()
    queue = list(dict.fromkeys(root_repos))

    while queue:
        repo = queue.pop(0)
        if repo in visited:
            continue
        visited.add(repo)

        node = load_submodule_node(redis, repo)
        if not node_is_available(node):
            logger.warning("Skipping unavailable or missing submodule info for {}", repo)
            continue

        child_repos = available_submodule_repos(redis, node, head_only=head_only)
        if child_repos:
            selected[repo] = SubmodulePlaybookSource(
                repo=repo,
                repo_url=source_url(repo, node),
                available_submodule_count=len(child_repos),
            )

        queue.extend(child_repo for child_repo in child_repos if child_repo not in visited)

    return [
        selected[repo]
        for repo in sorted(selected)
    ]


def build_playbook_yaml(sources: list[SubmodulePlaybookSource], limit: int) -> str:
    lines = [
        "playbook:",
        "  config:",
        "    conflict-type-percentages:",
    ]
    for conflict_type, percentage in SUBMODULE_CONFLICT_TYPE_PERCENTAGES.items():
        lines.append(f"      {conflict_type}: {percentage}")

    lines.append("  sources:")
    for source in sources:
        lines.extend(
            [
                f"    - repo_url: {source.repo_url}",
                f"      limit: {limit}",
            ]
        )

    return "\n".join(lines) + "\n"


def resolve_output_path(output: str, playbooks_dir: Path) -> Path:
    output_path = Path(output)
    if output_path.parent != Path("."):
        return output_path

    return playbooks_dir / output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a raw submodule playbook from repositories referenced by another playbook "
            "and synced info:submodule Redis data."
        )
    )
    parser.add_argument(
        "playbook",
        help="Input playbook name or path, for example top100raw",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output playbook path. Bare file names are saved under $PLAYBOOKS. Defaults to {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Conflict limit to write for each selected repository",
    )
    parser.add_argument(
        "--head",
        action="store_true",
        help="Only consider submodule dependencies present in the latest commit",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write generated YAML to stdout instead of a file",
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

    root_urls = load_root_repo_urls(playbook_path, cache_dir)
    if not root_urls:
        logger.error("No repositories found for playbook: {}", playbook_path)
        return 1

    redis = setup_redis_connection()
    sources = collect_submodule_playbook_sources(
        redis,
        [repo_cache_key(url) for url in root_urls],
        head_only=args.head,
    )
    if not sources:
        logger.error("No available submodule-owning repositories found for {}", playbook_path)
        return 1

    yaml = build_playbook_yaml(sources, args.limit)
    if args.stdout:
        print(yaml, end="")
        return 0

    output_path = resolve_output_path(args.output, playbooks_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml, encoding="utf-8")
    logger.info("Wrote {} repositories to {}", len(sources), output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
