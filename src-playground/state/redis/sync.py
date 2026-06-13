#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from state.redis._data import (
    SEMANTIC_SAVE_NAME,
    iter_matching_keys,
    resolve_sync_save_paths,
    restore_key,
    setup_data_redis_connection,
)


def collect_save_paths(save_or_playbooks: list[str]) -> list[Path]:
    save_paths: list[Path] = []
    seen: set[Path] = set()

    for save_or_playbook in save_or_playbooks:
        for save_path in resolve_sync_save_paths(save_or_playbook):
            if save_path in seen:
                continue
            seen.add(save_path)
            save_paths.append(save_path)

    return save_paths


def print_sync_plan(save_paths: list[Path]) -> None:
    print("Redis sync will prune all current Redis data and import these save files:")
    for save_path in save_paths:
        print(f"  {save_path.name}")


def confirm_sync() -> bool:
    answer = input("Continue? Type 'yes' to proceed: ")
    return answer == "yes"


def prune_all(redis) -> int:
    deleted_count = 0
    for key in iter_matching_keys(redis, ["*"]):
        deleted_count += redis.delete(key)
    return deleted_count


def import_save(redis, save_path: Path) -> int:
    imported_count = 0
    with open(save_path, "r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
                restore_key(redis, record)
            except Exception as error:
                raise RuntimeError(f"Failed to import {save_path}:{line_number}: {error}") from error

            imported_count += 1

    return imported_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace Redis data with one or more saved Redis dumps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""examples:
  state-redis-sync all
  state-redis-sync submodule
  state-redis-sync submodule --yes

Semantic playbook saves use: {SEMANTIC_SAVE_NAME}
When given a playbook name, this command loads the highest major version and
the highest minor version per data type within that major.
""",
    )
    parser.add_argument(
        "save_or_playbook",
        nargs="+",
        help="Exact save name, or playbook name using semantic saves",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Proceed without an interactive confirmation prompt",
    )
    args = parser.parse_args()

    try:
        save_paths = collect_save_paths(args.save_or_playbook)
    except FileNotFoundError as error:
        logger.error(str(error))
        return 2

    print_sync_plan(save_paths)
    if not args.yes and not confirm_sync():
        logger.warning("Redis sync cancelled")
        return 1

    redis = setup_data_redis_connection()
    deleted_count = prune_all(redis)
    logger.info(f"{deleted_count} Redis data keys deleted")

    total_imported = 0
    for save_path in save_paths:
        imported_count = import_save(redis, save_path)
        total_imported += imported_count
        logger.info(f"{imported_count} Redis data keys imported from {save_path}")

    logger.info(f"{total_imported} Redis data keys imported from {len(save_paths)} save files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
