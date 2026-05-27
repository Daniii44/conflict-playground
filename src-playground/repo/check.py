#!/usr/bin/env python3

import os
import sys
from pathlib import Path

from loguru import logger


INVALID_HEAD_REF = "ref: refs/heads/.invalid"


def iter_bare_repos(repos_dir: Path):
    for head_file in repos_dir.rglob("HEAD"):
        repo_dir = head_file.parent
        if (repo_dir / "objects").is_dir():
            yield repo_dir, head_file


def main() -> int:
    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    repos_dir = caches / "repos"

    if not repos_dir.is_dir():
        logger.error("Repository cache directory does not exist: {}", repos_dir)
        return 1

    invalid_repos = []
    for repo_dir, head_file in iter_bare_repos(repos_dir):
        try:
            head = head_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            logger.warning("Failed to read {}: {}", head_file, error)
            continue

        if head == INVALID_HEAD_REF:
            invalid_repos.append(repo_dir.relative_to(repos_dir))

    for repo in sorted(invalid_repos):
        print(repo)

    if invalid_repos:
        logger.error("{} repos have invalid HEAD refs", len(invalid_repos))
        return 1

    logger.info("No repos with invalid HEAD refs found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
