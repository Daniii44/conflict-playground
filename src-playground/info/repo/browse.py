#!/usr/bin/env python3

import requests
from redis.commands.json.path import Path
from common.redis_util import setup_redis_connection

def get_popular_repos(limit=10):
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PopularRepoFetcherApp"
    }

    filtered_repos = []
    page = 1
    per_page = min(limit, 100)  # GitHub caps per_page at 100

    try:
        while len(filtered_repos) < limit:
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

        return filtered_repos

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return []

def store_repos(repos: list) -> None:
    redis = setup_redis_connection()
    for repo in repos:
        key = f"info:repo:{repo['full_name']}"
        redis.json().set(key, Path.root_path(), repo)

if __name__ == "__main__":
    repos = get_popular_repos(limit=1000)
    store_repos(repos)