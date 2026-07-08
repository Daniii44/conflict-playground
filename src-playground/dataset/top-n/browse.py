#!/usr/bin/env python3

import argparse
import os
import requests
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


def get_popular_repos(limit: int = 10) -> list[dict]:
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
    args = parser.parse_args()

    repos = get_popular_repos(limit=args.count)
    store_repos(repos)

    for idx, repo in enumerate(repos, 1):
        print(f"{idx}. {repo['full_name']}")
        print(f"   Stars:     {repo['star_count']:,}")
        print(f"   Clone URL: {repo['clone_url']}")
        print(f"   Size:      {repo['size_kb']} KB (~{repo['size_mb']} MB)")
        print("-" * 50)


if __name__ == "__main__":
    main()
