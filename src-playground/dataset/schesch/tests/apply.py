#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

from common.git_util import capture_git, git_env
from common.redis_util import setup_redis_connection
from dataset.schesch.merge_lookup import resolve_unique_merge_sha_from_parents
from dataset.schesch.tests.generate import ScheschGeneratedTests, generated_patch_bytes, generated_tests_record_key


def resolve_playground_path(playground: str | None) -> Path:
    if playground is None:
        return Path.cwd()

    path = Path(playground)
    if path.is_absolute():
        return path

    playgrounds = os.environ.get("PLAYGROUNDS")
    if not playgrounds:
        raise RuntimeError("PLAYGROUNDS environment variable is not set")
    return Path(playgrounds) / playground


def ensure_git_worktree(playground_path: Path) -> None:
    if not playground_path.is_dir():
        raise RuntimeError(f"Playground path does not exist: {playground_path}")
    capture_git("-C", str(playground_path), "rev-parse", "--is-inside-work-tree")


def ensure_clean_worktree(playground_path: Path) -> None:
    status = capture_git("-C", str(playground_path), "status", "--porcelain")
    if status.stdout.strip():
        raise RuntimeError(
            "Refusing to apply generated tests because the playground worktree is not clean"
        )


def load_generated_tests(redis, key: str) -> ScheschGeneratedTests:
    payload = redis.json().get(key)
    if not payload:
        raise RuntimeError(f"No generated Schesch test suite found at {key}")

    record = ScheschGeneratedTests.model_validate(payload)
    if record.error:
        raise RuntimeError(f"Generated test suite at {key} has an error: {record.error}")
    if generated_patch_bytes(record) is None:
        raise RuntimeError(f"Generated test suite at {key} has no patch")
    return record


def abort_git_am(playground_path: Path) -> None:
    capture_git("-C", str(playground_path), "am", "--abort", check=False)


def apply_patch_to_current_head(playground_path: Path, patch: bytes | str) -> str:
    ensure_git_worktree(playground_path)
    ensure_clean_worktree(playground_path)
    before_head = capture_git("-C", str(playground_path), "rev-parse", "HEAD").stdout.strip()
    patch_input = patch.encode("utf-8") if isinstance(patch, str) else patch

    result = subprocess.run(
        ["git", "am", "--3way"],
        cwd=playground_path,
        input=patch_input,
        text=False,
        capture_output=True,
        check=False,
        env=git_env(),
    )
    if result.returncode != 0:
        abort_git_am(playground_path)
        stderr = result.stderr.decode("utf-8", errors="replace").strip() if isinstance(result.stderr, bytes) else (result.stderr or "").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip() if isinstance(result.stdout, bytes) else (result.stdout or "").strip()
        error = stderr or stdout
        raise RuntimeError(f"Applying generated tests failed and was aborted: {error}")

    status = capture_git("-C", str(playground_path), "status", "--porcelain")
    unmerged = capture_git("-C", str(playground_path), "ls-files", "-u")
    if unmerged.stdout.strip():
        abort_git_am(playground_path)
        capture_git("-C", str(playground_path), "reset", "--hard", before_head, check=False)
        raise RuntimeError("Applying generated tests produced conflicts and was aborted")
    if status.stdout.strip():
        raise RuntimeError("Applying generated tests left unexpected uncommitted changes")

    return capture_git("-C", str(playground_path), "rev-parse", "HEAD").stdout.strip()


def apply_generated_tests(redis, key: str, playground: str | None = None) -> tuple[Path, str]:
    record = load_generated_tests(redis, key)
    playground_path = resolve_playground_path(playground)
    applied_commit = apply_patch_to_current_head(playground_path, generated_patch_bytes(record) or b"")
    return playground_path, applied_commit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply a generated Schesch test suite onto the current HEAD of a playground. "
            "The command requires a clean worktree and aborts git-am if applying the patch "
            "fails or creates conflicts."
        )
    )
    parser.add_argument("repo_name", nargs="?", help="Bare repository cache key, e.g. owner/repo.git")
    parser.add_argument("merge_sha", nargs="?", help="Merge commit SHA used by dataset-schesch-tests-generate")
    parser.add_argument(
        "--parents",
        nargs=2,
        metavar=("LEFT_SHA", "RIGHT_SHA"),
        help="Resolve the merge commit from a Schesch parent pair when merge_sha is omitted.",
    )
    parser.add_argument(
        "--key",
        help="Generated test suite Redis key. If provided, repo_name and merge_sha are not required.",
    )
    parser.add_argument(
        "--playground",
        help="Playground name under PLAYGROUNDS or an absolute path. Defaults to the current directory.",
    )
    return parser.parse_args()


def resolve_record_key(args: argparse.Namespace) -> str:
    if args.key:
        if args.repo_name or args.merge_sha or args.parents:
            raise RuntimeError("Specify either --key or repo/merge arguments, not both")
        return args.key

    if not args.repo_name:
        raise RuntimeError("Specify --key or repo_name")
    if args.merge_sha and args.parents:
        raise RuntimeError("Specify either merge_sha or --parents, not both")
    if not args.merge_sha and not args.parents:
        raise RuntimeError("Specify merge_sha or --parents")

    merge_sha = args.merge_sha or resolve_unique_merge_sha_from_parents(args.repo_name, tuple(args.parents))
    return generated_tests_record_key(args.repo_name, merge_sha)


def main() -> int:
    args = parse_args()
    try:
        key = resolve_record_key(args)
        playground_path, commit_sha = apply_generated_tests(
            setup_redis_connection(),
            key,
            args.playground,
        )
    except (RuntimeError, subprocess.CalledProcessError) as error:
        logger.error("{}", error)
        return 1

    print(f"{playground_path}")
    print(commit_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
