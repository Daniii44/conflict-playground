#!/usr/bin/env python3

import argparse
import json

from loguru import logger

from info.redis._data import (
    dump_key,
    iter_matching_keys,
    resolve_save_path,
    setup_data_redis_connection,
)


def main():
    parser = argparse.ArgumentParser(
        description="Save Redis data keys to an NDJSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  info-redis-save all
  info-redis-save conflicts 'info:conflict:*'
""",
    )
    parser.add_argument("save_name", help="Name for the save file under $STORES/redis-saves")
    parser.add_argument(
        "patterns",
        nargs="*",
        default=["*"],
        help="Redis key wildcard patterns to save (default: *)",
    )
    args = parser.parse_args()

    redis = setup_data_redis_connection()
    output_path = resolve_save_path(args.save_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    saved_count = 0

    with open(output_path, "w", encoding="utf-8") as output:
        for key in iter_matching_keys(redis, args.patterns):
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

    logger.info(f"{saved_count} Redis data keys saved to {output_path}")


if __name__ == "__main__":
    main()
