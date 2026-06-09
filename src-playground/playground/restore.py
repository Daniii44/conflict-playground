#!/usr/bin/env python3

import argparse
import base64
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from common.git_util import capture_git


def resolve_playground_path(playground_name: str) -> Path:
    playgrounds = os.environ.get("PLAYGROUNDS")
    if not playgrounds:
        raise RuntimeError("PLAYGROUNDS environment variable is not set")

    playground_path = Path(playground_name)
    if playground_path.is_absolute() or ".." in playground_path.parts:
        raise RuntimeError("Expected a playground name, not a filesystem path")

    return Path(playgrounds) / playground_name


def safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = tar.getmembers()
    for member in members:
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"Unsafe archive member path: {member.name}")
        if not member_path.parts or member_path.parts[0] != ".git":
            raise RuntimeError(f"Archive member is outside .git: {member.name}")
    return members


def restore_archive(playground_path: Path, encoded_archive: str) -> None:
    try:
        archive = base64.b64decode(encoded_archive, validate=True)
    except ValueError as error:
        raise RuntimeError(f"Could not decode base64 archive: {error}") from error

    playground_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="playground-restore-") as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "resolution.tar.gz"
        archive_path.write_bytes(archive)

        try:
            with tarfile.open(archive_path, mode="r:gz") as tar:
                members = safe_members(tar)
                tar.extractall(temp_path, members=members)
        except tarfile.TarError as error:
            raise RuntimeError(f"Could not extract archive: {error}") from error

        restored_git = temp_path / ".git"
        if not restored_git.is_dir():
            raise RuntimeError("Archive does not contain a .git directory")

        target_git = playground_path / ".git"
        if target_git.exists() or target_git.is_symlink():
            shutil.rmtree(target_git)
        shutil.move(str(restored_git), str(target_git))

    result = capture_git("-C", str(playground_path), "reset", "--hard", check=False)
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Could not reset restored playground worktree: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a playground .git directory from a base64 tar.gz archive on stdin")
    parser.add_argument("playground", help="Playground name")
    args = parser.parse_args()

    try:
        restore_archive(resolve_playground_path(args.playground), sys.stdin.read())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
