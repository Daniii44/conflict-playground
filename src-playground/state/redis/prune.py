#!/usr/bin/env python3

import argparse
import os
from pathlib import Path
import sys
from typing import Iterable

from loguru import logger

from common.playbook import load_playbook_data, resolve_playbook_path
from common.repo_cache import repo_cache_key
from playbook.playgrounds import playground_from_override, resolve_playground_merge_sha
from state.redis._data import iter_matching_keys, setup_data_redis_connection


def key_text(key: bytes | str) -> str | None:
    if isinstance(key, str):
        return key

    try:
        return key.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect_exclusive_playbook_identifiers(playbook: str) -> set[str]:
    playbooks = os.environ.get("PLAYBOOKS")
    if not playbooks:
        raise RuntimeError("PLAYBOOKS environment variable is not set")
    playbooks_dir = Path(playbooks)
    playbook_path = resolve_playbook_path(playbook, playbooks_dir)
    data = load_playbook_data(playbook_path)
    sources = data.get("playbook", {}).get("sources")
    if not sources:
        raise ValueError(
            f"Refusing to prune with --not-in-playground for {playbook!r}: "
            "playbook must define sources with override_merge_shas only"
        )

    identifiers: list[str] = []
    for source in sources:
        if not isinstance(source, dict) or not source.get("repo_url"):
            raise ValueError(
                f"Refusing to prune with --not-in-playground for {playbook!r}: "
                "every source must define repo_url and override_merge_shas only"
            )

        overrides = source.get("override_merge_shas")
        if not isinstance(overrides, list) or not overrides:
            raise ValueError(
                f"Refusing to prune with --not-in-playground for {playbook!r}: "
                "every source must define non-empty override_merge_shas"
            )

        repo_name = repo_cache_key(source["repo_url"])
        for override in overrides:
            playground = playground_from_override(repo_name, override)
            merge_sha = resolve_playground_merge_sha(playground)
            identifiers.append(f"{repo_name}:{merge_sha}")

    return set(identifiers)


def key_is_in_playgrounds(key: bytes | str, playground_identifiers: Iterable[str]) -> bool:
    text = key_text(key)
    if text is None:
        return False

    return any(identifier in text for identifier in playground_identifiers)


def main():
    parser = argparse.ArgumentParser(
        description="Delete Redis data keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  state-redis-prune --all
  state-redis-prune 'info:conflict:*'
  state-redis-prune 'info:conflict:*' --not-in-playground schesch
""",
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        help="Redis key wildcard patterns to delete, e.g. info:conflict:*",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Delete all Redis data keys",
    )
    parser.add_argument(
        "--not-in-playground",
        metavar="PLAYBOOK",
        help=(
            "Only delete matched keys that do not contain any "
            "'owner/repo.git:merge_sha' identifier from the playbook's "
            "override_merge_shas entries"
        ),
    )
    args = parser.parse_args()

    if args.all and args.patterns:
        logger.error("Use either --all or explicit patterns, not both")
        sys.exit(1)

    if not args.all and not args.patterns:
        logger.error("Either --all or at least one pattern must be provided")
        sys.exit(1)

    patterns = ["*"] if args.all else args.patterns
    playground_identifiers: set[str] | None = None
    if args.not_in_playground:
        try:
            playground_identifiers = collect_exclusive_playbook_identifiers(args.not_in_playground)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            logger.error(str(exc))
            sys.exit(1)

    redis = setup_data_redis_connection()
    deleted_count = 0

    for key in iter_matching_keys(redis, patterns):
        if playground_identifiers is not None and key_is_in_playgrounds(key, playground_identifiers):
            continue
        deleted_count += redis.delete(key)

    logger.info(f"{deleted_count} Redis data keys deleted")


if __name__ == "__main__":
    main()
