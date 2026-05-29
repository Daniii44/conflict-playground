#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from loguru import logger

from common.git_util import capture_git
from common.repo_cache import repo_cache_key, resolve_submodule_url


MAX_SUBMODULE_DEPTH = 20


def playground_name(repo_name: str, merge_sha: str) -> str:
    return f"{repo_name}-{merge_sha}"


def alternate_path(bare_repo: Path, clone_path: Path) -> str:
    abs_path = (bare_repo / "objects").resolve()
    clone_objects = (clone_path / ".git" / "objects").resolve()
    rel_path = os.path.relpath(abs_path, clone_objects)
    return (
        rel_path
        .replace("caches-bind-mount", "caches")
        .replace("caches-named-volume", "caches")
    )


def list_submodules(gitmodules_path: Path) -> list[tuple[str, str, str]]:
    result = capture_git(
        "config",
        "-f",
        str(gitmodules_path),
        "--get-regexp",
        r"^submodule\..*\.path$",
        check=False,
    )

    if result.returncode != 0:
        logger.warning(
            "Skipping submodule setup for {} because .gitmodules is not parseable",
            gitmodules_path.parent,
        )
        return []

    submodules = []
    for line in result.stdout.splitlines():
        key, submodule_path = line.split(" ", 1)
        submodule_name = key.removeprefix("submodule.").removesuffix(".path")
        url_result = capture_git(
            "config",
            "-f",
            str(gitmodules_path),
            "--get",
            f"submodule.{submodule_name}.url",
            check=False,
        )

        submodule_url = url_result.stdout.strip()
        if not submodule_url:
            logger.warning("Skipping submodule without URL: {}", submodule_path)
            continue

        submodules.append((submodule_name, submodule_path, submodule_url))

    return submodules


def clean_gitlink_sha(repo_path: Path, submodule_path: str) -> str | None:
    result = capture_git(
        "-C",
        str(repo_path),
        "ls-files",
        "-s",
        "--",
        submodule_path,
        check=False,
    )

    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == "160000" and fields[2] == "0":
            return fields[1]

    return None


def cached_repo_for_url(repo_cache_dir: Path, url: str) -> Path | None:
    cache_repo = repo_cache_dir / repo_cache_key(url)
    if cache_repo.is_dir():
        return cache_repo
    return None


def is_initialized_submodule(repo_path: Path, submodule_name: str) -> bool:
    result = capture_git(
        "-C",
        str(repo_path),
        "config",
        "--get",
        f"submodule.{submodule_name}.url",
        check=False,
    )
    return result.returncode == 0


def init_submodules_with_alternates(
    repo_path: Path,
    parent_url: str,
    repo_cache_dir: Path,
    *,
    depth: int = 0,
) -> None:
    if depth > MAX_SUBMODULE_DEPTH:
        logger.warning("Skipping deeply nested submodules below {}", repo_path)
        return

    gitmodules_path = repo_path / ".gitmodules"
    if not gitmodules_path.is_file():
        return

    for submodule_name, submodule_path, submodule_url in list_submodules(gitmodules_path):
        resolved_url = resolve_submodule_url(parent_url, submodule_url)
        cache_repo = cached_repo_for_url(repo_cache_dir, resolved_url)

        if cache_repo is None:
            logger.warning("Skipping uncached submodule: {} ({})", submodule_path, resolved_url)
            continue

        if clean_gitlink_sha(repo_path, submodule_path) is None:
            logger.error(
                "Unmerged submodule found: '{}'. init should be called before the merge",
                submodule_path,
            )
            continue

        submodule_is_initialized = is_initialized_submodule(repo_path, submodule_name)
        if submodule_is_initialized:
            logger.debug("Updating already initialized submodule: {}", submodule_path)
            update_args = [
                "-C",
                str(repo_path),
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "update",
                "--",
                submodule_path,
            ]
        else:
            logger.info("Initializing submodule from cache: {}", submodule_path)
            capture_git(
                "-C",
                str(repo_path),
                "config",
                f"submodule.{submodule_name}.url",
                str(cache_repo),
            )
            update_args = [
                "-C",
                str(repo_path),
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "update",
                "--init",
                "--reference",
                str(cache_repo),
                "--",
                submodule_path,
            ]

        result = capture_git(*update_args, check=False)

        if result.returncode != 0:
            logger.warning("Failed to update submodule from cache: {}", submodule_path)
            if result.stderr:
                logger.debug(result.stderr.rstrip())
            continue

        submodule_repo_path = repo_path / submodule_path
        is_worktree = capture_git(
            "-C",
            str(submodule_repo_path),
            "rev-parse",
            "--is-inside-work-tree",
            check=False,
        )
        if is_worktree.returncode != 0:
            continue

        if not submodule_is_initialized:
            capture_git(
                "-C",
                str(submodule_repo_path),
                "remote",
                "set-url",
                "origin",
                resolved_url,
                check=False,
            )
        init_submodules_with_alternates(
            submodule_repo_path,
            resolved_url,
            repo_cache_dir,
            depth=depth + 1,
        )


def setup_playground(repo_name: str, merge_sha: str) -> str:
    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
    repo_cache_dir = caches / "repos"
    bare_repo = repo_cache_dir / repo_name
    name = playground_name(repo_name, merge_sha)
    clone_path = playgrounds / name

    if not bare_repo.is_dir():
        raise RuntimeError(f"Bare repository {bare_repo} does not exist")

    parents = capture_git(
        f"--git-dir={bare_repo}",
        "show",
        "-s",
        "--format=%P",
        merge_sha,
    ).stdout.split()

    if len(parents) != 2:
        raise RuntimeError(
            f"Only merge commits with exactly two parents are supported (found {len(parents)})"
        )

    rev_list = capture_git(
        f"--git-dir={bare_repo}",
        "rev-list",
        "--parents",
        "-n",
        "1",
        merge_sha,
    ).stdout.split()
    _, first_parent, second_parent = rev_list

    main_parent = second_parent
    feature_parent = first_parent

    playgrounds.mkdir(parents=True, exist_ok=True)
    if clone_path.is_dir():
        shutil.rmtree(clone_path)

    clone_path.mkdir(parents=True)
    capture_git("init", cwd=clone_path)

    alternates = clone_path / ".git" / "objects" / "info" / "alternates"
    alternates.write_text(f"{alternate_path(bare_repo, clone_path)}\n")

    superproject_url = capture_git(
        "-C",
        str(bare_repo),
        "config",
        "--get",
        "remote.origin.url",
        check=False,
    ).stdout.strip()

    if superproject_url:
        capture_git("checkout", "-b", "feature", feature_parent, cwd=clone_path)
        init_submodules_with_alternates(clone_path, superproject_url, repo_cache_dir)

        capture_git("checkout", "-b", "main", main_parent, cwd=clone_path)
        init_submodules_with_alternates(clone_path, superproject_url, repo_cache_dir)
    else:
        logger.warning("Skipping submodule setup because cached repo has no origin URL: {}", bare_repo)
        capture_git("checkout", "-b", "feature", feature_parent, cwd=clone_path)
        capture_git("checkout", "-b", "main", main_parent, cwd=clone_path)

    capture_git("merge", "feature", cwd=clone_path, check=False)

    return name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an isolated merge-conflict playground")
    parser.add_argument("repo_name", help="Bare repository cache key, e.g. qt/qt5.git")
    parser.add_argument("merge_sha", help="Merge commit SHA")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sys.stdout.write(f"{setup_playground(args.repo_name, args.merge_sha)}\n")
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as e:
        logger.error("{}", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
