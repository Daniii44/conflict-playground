#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from state.redis._data import (
    SEMANTIC_SAVE_NAME,
    dump_key,
    iter_matching_keys,
    resolve_save_path,
    setup_data_redis_connection,
)


def write_save(redis, output_path: Path, patterns: list[str]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    saved_count = 0

    with open(output_path, "w", encoding="utf-8") as output:
        for key in iter_matching_keys(redis, patterns):
            try:
                record = dump_key(redis, key)
            except Exception as error:
                logger.warning(f"Skipping Redis key because it could not be dumped: {error}")
                continue

            if record is None:
                continue

            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            output.write("\n")
            saved_count += 1

    return saved_count


def main():
    parser = argparse.ArgumentParser(
        description="Save Redis data keys to an NDJSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""examples:
  state-redis-save submodule-info-v1 'info:*'
  state-redis-save submodule-resolution-v1 'resolution:*'
  state-redis-save submodule-evaluation-v1.1 'evaluation:*'

Semantic playbook saves use: {SEMANTIC_SAVE_NAME}
""",
    )
    parser.add_argument("save_name", help="Name for the save file under $STORES/redis-saves")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite the save file if it already exists",
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        default=["*"],
        help="Redis key wildcard patterns to save (default: *)",
    )
    args = parser.parse_args()

    output_path = resolve_save_path(args.save_name)
    if output_path.exists() and not args.force:
        logger.error(f"Redis save already exists: {args.save_name} (use --force to overwrite)")
        sys.exit(1)

    redis = setup_data_redis_connection()
    saved_count = write_save(redis, output_path, args.patterns)
    logger.info(f"{saved_count} Redis data keys saved to {output_path}")


if __name__ == "__main__":
    main()
