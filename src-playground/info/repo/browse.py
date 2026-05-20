#!/usr/bin/env python3

import base64
import configparser
import os
import re
import requests
from loguru import logger
from redis.commands.json.path import Path
from common.redis_util import setup_redis_connection


def _make_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PopularRepoFetcherApp",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.debug("Using GitHub token authentication")
    else:
        logger.debug("No GitHub token configured; using unauthenticated requests")
    return headers


def get_popular_repos(limit=10):
    logger.info(f"Fetching up to {limit} popular GitHub repositories")
    url = "https://api.github.com/search/repositories"
    headers = _make_headers()
    filtered_repos = []
    page = 1
    per_page = min(limit, 100)  # GitHub caps per_page at 100

    try:
        while len(filtered_repos) < limit:
            logger.debug(f"Fetching repository search page {page}")
            params = {
                "q": "stars:>10000",
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            }
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()

            items = response.json().get("items", [])
            if not items:
                logger.warning(f"GitHub repository search returned no items on page {page}")
                break

            for repo in items:
                size_kb = repo.get("size", 0)
                filtered_repos.append({
                    "full_name": repo.get("full_name"),
                    "star_count": repo.get("stargazers_count"),
                    "clone_url": repo.get("clone_url"),
                    "size_kb": size_kb,
                    "size_mb": round(size_kb / 1024, 2),
                })
                if len(filtered_repos) == limit:
                    break

            page += 1

        logger.info(f"Fetched {len(filtered_repos)} popular repositories")
        return filtered_repos

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch popular repositories: {e}")
        return []


def _parse_gitmodules(content: str) -> list[dict]:
    config = configparser.RawConfigParser()
    config.read_string(content)
    submodules = []
    for section in config.sections():
        if section.startswith("submodule"):
            submodules.append({
                "path": config.get(section, "path", fallback=None),
                "url": config.get(section, "url", fallback=None),
            })
    return submodules


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    match = re.match(
        r'(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?$', url
    )
    if match:
        return match.group(1), match.group(2)
    return None


def build_submodule_tree(owner: str, repo: str, headers: dict, _path: frozenset = frozenset()) -> dict:
    """Recursively build a submodule dependency tree for a GitHub repo.

    Uses the current DFS path (not a global visited set) so that a repo
    appearing as a submodule in multiple sibling branches is expanded in
    each, while true ancestor cycles are detected and marked with cycle=True.
    """
    full_name = f"{owner}/{repo}"

    if full_name in _path:
        logger.warning(f"Detected submodule cycle at {full_name}")
        return {"repo": full_name, "cycle": True, "submodules": []}

    logger.debug(f"Building submodule tree for {full_name}")
    node: dict = {"repo": full_name, "submodules": []}
    current_path = _path | {full_name}

    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/.gitmodules"
    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 404:
            logger.debug(f"No .gitmodules found for {full_name}")
            return node
        response.raise_for_status()

        content = base64.b64decode(response.json()["content"]).decode("utf-8")

        for sub in _parse_gitmodules(content):
            sub_url = sub.get("url", "")
            owner_repo = _github_owner_repo(sub_url)
            if owner_repo:
                sub_owner, sub_repo_name = owner_repo
                logger.debug(f"Following submodule {sub.get('path')} from {full_name} to {sub_owner}/{sub_repo_name}")
                child = build_submodule_tree(sub_owner, sub_repo_name, headers, current_path)
            else:
                logger.warning(f"Could not parse GitHub owner/repo from submodule URL in {full_name}: {sub_url}")
                child = {"repo": None, "submodules": []}
            child["path"] = sub.get("path")
            child["url"] = sub_url
            node["submodules"].append(child)

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch .gitmodules for {full_name}: {e}")

    return node


def store_repos(repos: list) -> None:
    logger.info(f"Storing {len(repos)} repositories in Redis")
    redis = setup_redis_connection()
    for repo in repos:
        key = f"info:repo:{repo['full_name']}"
        redis.json().set(key, Path.root_path(), repo)
        logger.debug(f"Stored repository metadata at {key}")


if __name__ == "__main__":
    headers = _make_headers()
    repos = get_popular_repos(limit=100)

    for repo in repos:
        owner, name = repo["full_name"].split("/", 1)
        logger.info(f"Collecting submodule metadata for {repo['full_name']}")
        repo["submodule_tree"] = build_submodule_tree(owner, name, headers)

    store_repos(repos)

    for idx, repo in enumerate(repos, 1):
        has_subs = bool(repo["submodule_tree"].get("submodules"))
        print(f"{idx}. {repo['full_name']} {'(has submodules)' if has_subs else ''}")
        print(f"   Stars:     {repo['star_count']:,}")
        print(f"   Clone URL: {repo['clone_url']}")
        print(f"   Size:      {repo['size_kb']} KB (~{repo['size_mb']} MB)")
        print("-" * 50)
