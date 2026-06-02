#!/usr/bin/env python3

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from loguru import logger

from common.playbook import load_playbook_repo_urls, resolve_playbook_path
from common.repo_cache import repo_cache_key


GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
QUERY_BATCH_SIZE = 50


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class RepoDiskUsage:
    repo: GitHubRepo
    disk_usage_kib: int


def github_token() -> str:
    token = os.environ.get("GH_GRAPHQL_TOKEN")
    if not token:
        raise RuntimeError("Set gh_graphql_token in config.yaml or export GH_GRAPHQL_TOKEN")
    return token


def github_repo_from_url(repo_url: str) -> GitHubRepo | None:
    parsed = urlsplit(repo_url)
    if parsed.netloc and parsed.netloc.lower() != "github.com":
        return None

    if not parsed.scheme and ":" in repo_url and "/" not in repo_url.split(":", 1)[0]:
        ssh_host = repo_url.split(":", 1)[0].split("@")[-1]
        if ssh_host.lower() != "github.com":
            return None

    repo_key = repo_cache_key(repo_url)
    if not repo_key.endswith(".git"):
        return None

    parts = repo_key.removesuffix(".git").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None

    return GitHubRepo(owner=parts[0], name=parts[1])


def unique_github_repos(repo_urls: list[str]) -> list[GitHubRepo]:
    repos = []
    seen = set()
    for repo_url in repo_urls:
        repo = github_repo_from_url(repo_url)
        if repo is None:
            logger.warning("Skipping non-GitHub or unsupported repository URL: {}", repo_url)
            continue

        key = repo.full_name.lower()
        if key in seen:
            continue

        seen.add(key)
        repos.append(repo)

    return repos


def alias_for(index: int) -> str:
    return f"repo{index}"


def build_disk_usage_query(repos: list[GitHubRepo]) -> str:
    fields = []
    for index, repo in enumerate(repos):
        fields.append(
            f'{alias_for(index)}: repository(owner: "{repo.owner}", name: "{repo.name}") '
            "{ nameWithOwner diskUsage }"
        )

    return "query RepositoryDiskUsage {\n" + "\n".join(fields) + "\n}"


def graphql_request(query: str, token: str) -> dict:
    response = requests.post(
        GITHUB_GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"query": query},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors") and not payload.get("data"):
        messages = "; ".join(error.get("message", str(error)) for error in payload["errors"])
        raise RuntimeError(f"GitHub GraphQL query failed: {messages}")
    for error in payload.get("errors", []):
        logger.warning("GitHub GraphQL warning: {}", error.get("message", error))
    return payload


def fetch_disk_usage(repos: list[GitHubRepo], token: str) -> list[RepoDiskUsage]:
    usages = []
    for offset in range(0, len(repos), QUERY_BATCH_SIZE):
        batch = repos[offset : offset + QUERY_BATCH_SIZE]
        payload = graphql_request(build_disk_usage_query(batch), token)
        data = payload.get("data") or {}

        for index, repo in enumerate(batch):
            value = data.get(alias_for(index))
            if value is None:
                logger.warning("GitHub returned no repository data for {}", repo.full_name)
                continue

            disk_usage = value.get("diskUsage")
            if not isinstance(disk_usage, int):
                logger.warning("GitHub returned no diskUsage for {}", repo.full_name)
                continue

            usages.append(RepoDiskUsage(repo=repo, disk_usage_kib=disk_usage))

    return usages


def format_size(kib: int) -> str:
    bytes_value = kib * 1024
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(bytes_value)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024

    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.2f} {unit}"


def print_text(usages: list[RepoDiskUsage]) -> None:
    total_kib = sum(usage.disk_usage_kib for usage in usages)
    for usage in usages:
        print(f"{usage.repo.full_name}\t{usage.disk_usage_kib} KiB\t{format_size(usage.disk_usage_kib)}")

    print(f"total\t{total_kib} KiB\t{format_size(total_kib)}")


def print_json(usages: list[RepoDiskUsage]) -> None:
    total_kib = sum(usage.disk_usage_kib for usage in usages)
    print(
        json.dumps(
            {
                "repositories": [
                    {
                        "repo": usage.repo.full_name,
                        "disk_usage_kib": usage.disk_usage_kib,
                    }
                    for usage in usages
                ],
                "total_disk_usage_kib": total_kib,
            },
            sort_keys=True,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate the GitHub repository download size for a playbook."
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="default",
        help="Playbook name or path, defaults to default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    playbooks_dir = Path(os.environ.get("PLAYBOOKS", str(Path.home() / "playbooks")))
    playbook_path = resolve_playbook_path(args.playbook, playbooks_dir)
    if not playbook_path.is_file():
        logger.error("No such playbook: {}", playbook_path)
        return 1

    repos = unique_github_repos(load_playbook_repo_urls(playbook_path))
    if not repos:
        logger.error("No GitHub repositories found in playbook: {}", playbook_path)
        return 1

    try:
        usages = fetch_disk_usage(repos, github_token())
    except (requests.RequestException, RuntimeError) as error:
        logger.error("{}", error)
        return 1

    if args.json:
        print_json(usages)
    else:
        print_text(usages)

    return 0


if __name__ == "__main__":
    sys.exit(main())
