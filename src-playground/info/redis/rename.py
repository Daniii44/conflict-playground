#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from info.redis._data import resolve_save_path


def main():
    parser = argparse.ArgumentParser(description="Rename a Redis save file")
    parser.add_argument("old_name", help="Current save name under $CACHES/redis-saves")
    parser.add_argument("new_name", help="New save name under $CACHES/redis-saves")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite the target save if it already exists",
    )
    args = parser.parse_args()

    old_path = resolve_save_path(args.old_name)
    new_path = resolve_save_path(args.new_name)

    if not old_path.exists():
        logger.error(f"Redis save does not exist: {args.old_name}")
        sys.exit(1)

    if new_path.exists() and not args.force:
        logger.error(f"Redis save already exists: {args.new_name}")
        sys.exit(1)

    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.replace(new_path)
    logger.info(f"Renamed Redis save {args.old_name} to {args.new_name}")


if __name__ == "__main__":
    main()
