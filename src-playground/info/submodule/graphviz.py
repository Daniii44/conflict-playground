#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from redis import Redis

from common.playbook import resolve_playbook_path
from common.redis_util import INFO_SUBMODULE_PREFIX, setup_redis_connection
from common.repo_cache import repo_cache_key
from info.submodule.sync import load_root_repo_urls

GRAPHVIZ_STORE_DIR_NAME = "graphviz"


def dot_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def dot_attrs(attrs: dict[str, str | None]) -> str:
    clean_attrs = {key: value for key, value in attrs.items() if value is not None}
    if not clean_attrs:
        return ""

    rendered = ", ".join(
        f"{key}={dot_quote(value)}"
        for key, value in clean_attrs.items()
    )
    return f" [{rendered}]"


class SubmoduleGraph:
    def __init__(self, redis: Redis, *, head_only: bool = False):
        self.redis = redis
        self.head_only = head_only
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str, str | None]] = set()
        self.visited: set[str] = set()

    def collect(self, root_repo: str) -> None:
        self._collect_repo(root_repo)

    def _collect_repo(self, repo: str) -> None:
        if repo in self.visited:
            return
        self.visited.add(repo)

        node = self.load_node(repo)
        self.nodes[repo] = node

        for submodule in node.get("submodules", []):
            if self.head_only and not submodule.get("present_in_head", False):
                continue

            child_repo = submodule.get("repo")
            if not child_repo:
                continue

            label = submodule.get("path") or submodule.get("name") or ""
            self.edges.add((repo, child_repo, label, submodule.get("resolved_url")))
            self._collect_repo(child_repo)

    def load_node(self, repo: str) -> dict[str, Any]:
        node = self.redis.json().get(f"{INFO_SUBMODULE_PREFIX}{repo}")
        if isinstance(node, dict):
            return node

        return {
            "repo": repo,
            "unavailable": True,
            "missing_info": True,
            "submodules": [],
        }

    def to_dot(self, graph_name: str) -> str:
        lines = [
            f"digraph {dot_quote(graph_name)} {{",
            "  graph [rankdir=LR, overlap=false, splines=true];",
            "  node [shape=box, style=rounded, fontname=Helvetica];",
            "  edge [fontname=Helvetica];",
            "",
        ]

        for repo in sorted(self.nodes):
            node = self.nodes[repo]
            attrs = {
                "label": repo,
                "style": "rounded,dashed" if node.get("unavailable") else "rounded",
                "color": "gray50" if node.get("unavailable") else "black",
                "fontcolor": "gray35" if node.get("unavailable") else "black",
                "tooltip": node.get("url") or node.get("repo"),
            }
            if node.get("missing_info"):
                attrs["label"] = f"{repo}\nmissing info:submodule data"
            elif node.get("unavailable"):
                attrs["label"] = f"{repo}\nunavailable"

            lines.append(f"  {dot_quote(repo)}{dot_attrs(attrs)};")

        if self.edges:
            lines.append("")

        for parent, child, label, tooltip in sorted(self.edges):
            lines.append(
                f"  {dot_quote(parent)} -> {dot_quote(child)}"
                f"{dot_attrs({'label': label, 'tooltip': tooltip})};"
            )

        lines.append("}")
        return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Graphviz DOT for submodule metadata recorded by info-submodule-sync"
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="default",
        help="Playbook name or path, defaults to default",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write DOT output to this file instead of stdout. Bare file names are saved under $STORES/graphviz",
    )
    parser.add_argument(
        "--head",
        action="store_true",
        help="Only show submodule dependencies present in the latest commit",
    )
    return parser.parse_args()


def resolve_output_path(output: str) -> Path:
    output_path = Path(output)
    if output_path.parent != Path("."):
        return output_path

    stores_dir = Path(os.environ.get("STORES", "../../data/stores"))
    return stores_dir / GRAPHVIZ_STORE_DIR_NAME / output_path


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

    graph = SubmoduleGraph(setup_redis_connection(), head_only=args.head)
    for url in root_urls:
        graph.collect(repo_cache_key(url))

    dot = graph.to_dot(playbook_path.stem)
    if args.output:
        output_path = resolve_output_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{dot}\n", encoding="utf-8")
    else:
        print(dot)

    return 0


if __name__ == "__main__":
    sys.exit(main())
