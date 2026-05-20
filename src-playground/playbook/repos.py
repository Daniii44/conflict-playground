#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


def get_repo_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    repo_name = parsed.path.strip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return repo_name


def load_playbook_repos(playbook_path: Path) -> list[str]:
    with playbook_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    sources = data.get("playbook", {}).get("sources") or []
    repos = []
    seen = set()
    for source in sources:
        repo_url = source.get("repo_url")
        if not repo_url:
            continue

        repo_name = get_repo_name_from_url(repo_url)
        if repo_name in seen:
            continue

        repos.append(repo_name)
        seen.add(repo_name)

    return repos


def main() -> None:
    parser = argparse.ArgumentParser(description="List repositories attached to a playbook")
    parser.add_argument("playbook", nargs="?", default="default", help="Name of the playbook")
    args = parser.parse_args()

    playbooks = os.environ.get("PLAYBOOKS")
    if not playbooks:
        print("PLAYBOOKS environment variable is not set", file=sys.stderr)
        sys.exit(1)

    playbook_path = Path(playbooks) / f"{args.playbook}.yaml"
    if not playbook_path.is_file():
        print(f"No such playbook: {playbook_path}", file=sys.stderr)
        sys.exit(1)

    for repo in load_playbook_repos(playbook_path):
        print(repo)


if __name__ == "__main__":
    main()
