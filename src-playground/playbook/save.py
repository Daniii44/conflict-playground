#!/usr/bin/env python3

import argparse
import base64
import io
import os
import sys
import tarfile
from pathlib import Path


def resolve_playground_path(playground: str) -> Path:
    path = Path(playground)
    if path.is_dir():
        return path

    playgrounds = os.environ.get("PLAYGROUNDS")
    if playgrounds:
        return Path(playgrounds) / playground

    return path


def should_archive(member_path: Path) -> bool:
    if member_path.name == "index":
        return False

    if "hooks" in member_path.parts:
        return False

    return True


def build_archive(playground_path: Path) -> bytes:
    git_path = playground_path / ".git"
    if not git_path.is_dir():
        raise RuntimeError(f"{playground_path} is not a playground with a .git directory")

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for path in sorted(git_path.rglob("*")):
            relative_path = path.relative_to(playground_path)
            if not should_archive(relative_path):
                continue
            tar.add(path, arcname=relative_path, recursive=False)

    return archive.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a base64 tar.gz archive of a playground .git directory")
    parser.add_argument("playground", help="Playground name or path")
    args = parser.parse_args()

    try:
        archive = build_archive(resolve_playground_path(args.playground))
    except RuntimeError as error:
        print(error, file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(base64.b64encode(archive).decode("ascii"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
