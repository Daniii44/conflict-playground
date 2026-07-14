#!/usr/bin/env python3

import argparse
import os
import requests
from typing import Optional
from loguru import logger
from redis.commands.json.path import Path
from common.redis_util import setup_redis_connection


DATASET_TOP_N_REPO_PREFIX = "dataset:top-n:repo:"


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


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("count must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("count must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("size must be greater than 0")
    return parsed


def repo_uses_submodules_in_head(
    full_name: str,
    *,
    headers: Optional[dict] = None,
    default_branch: Optional[str] = None,
) -> bool:
    request_headers = headers or _make_headers()
    params = {"ref": default_branch} if default_branch else None

    try:
        response = requests.get(
            f"https://api.github.com/repos/{full_name}/contents/.gitmodules",
            params=params,
            headers=request_headers,
        )
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to inspect head commit for submodules in {full_name}: {e}")
        return False

    if response.status_code == 404:
        logger.debug(f"No .gitmodules found in head commit for {full_name}")
        return False

    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to inspect head commit for submodules in {full_name}: {e}")
        return False

    logger.debug(f"Detected .gitmodules in head commit for {full_name}")
    return True


def get_popular_repos(limit: int = 10, max_size_gb: Optional[float] = None) -> list[dict]:
    logger.info(f"Fetching up to {limit} popular GitHub repositories")
    url = "https://api.github.com/search/repositories"
    headers = _make_headers()
    filtered_repos = []
    page = 1
    per_page = min(limit, 100)  # GitHub caps per_page at 100
    max_size_kb = round(max_size_gb * 1024 * 1024) if max_size_gb is not None else None
    if max_size_kb is not None:
        logger.info(f"Skipping repositories larger than {max_size_gb:g} GB")

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
                if max_size_kb is not None and size_kb > max_size_kb:
                    logger.debug(
                        f"Skipping {repo.get('full_name')} because size is {size_kb} KB "
                        f"and maximum is {max_size_kb} KB"
                    )
                    continue

                uses_submodules_in_head = repo_uses_submodules_in_head(
                    repo.get("full_name"),
                    headers=headers,
                    default_branch=repo.get("default_branch"),
                )
                filtered_repos.append({
                    "full_name": repo.get("full_name"),
                    "star_count": repo.get("stargazers_count"),
                    "clone_url": repo.get("clone_url"),
                    "default_branch": repo.get("default_branch"),
                    "size_kb": size_kb,
                    "size_mb": round(size_kb / 1024, 2),
                    "uses_submodules_in_head": uses_submodules_in_head,
                })
                if len(filtered_repos) == limit:
                    break

            page += 1

        logger.info(f"Fetched {len(filtered_repos)} popular repositories")
        return filtered_repos

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch popular repositories: {e}")
        return []


def store_repos(repos: list) -> None:
    logger.info(f"Storing {len(repos)} repositories in Redis")
    redis = setup_redis_connection()
    for repo in repos:
        key = f"{DATASET_TOP_N_REPO_PREFIX}{repo['full_name']}"
        redis.json().set(key, Path.root_path(), repo)
        logger.debug(f"Stored repository metadata at {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch top N popular GitHub repositories into Redis")
    parser.add_argument("--count", type=positive_int, default=100, help="Number of repositories to fetch")
    parser.add_argument(
        "--max-size-gb",
        type=positive_float,
        help="Skip repositories larger than this size in GB",
    )
    args = parser.parse_args()

    repos = get_popular_repos(limit=args.count, max_size_gb=args.max_size_gb)
    store_repos(repos)

    for idx, repo in enumerate(repos, 1):
        print(f"{idx}. {repo['full_name']}")
        print(f"   Stars:     {repo['star_count']:,}")
        print(f"   Clone URL: {repo['clone_url']}")
        print(f"   Size:      {repo['size_kb']} KB (~{repo['size_mb']} MB)")
        print("-" * 50)


if __name__ == "__main__":
    main()
