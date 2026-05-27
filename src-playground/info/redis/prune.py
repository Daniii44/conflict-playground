#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from info.redis._data import iter_matching_keys, setup_data_redis_connection


def main():
    parser = argparse.ArgumentParser(
        description="Delete Redis data keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  info-redis-prune --all
  info-redis-prune 'info:conflict:*'
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
    args = parser.parse_args()

    if args.all and args.patterns:
        logger.error("Use either --all or explicit patterns, not both")
        sys.exit(1)

    if not args.all and not args.patterns:
        logger.error("Either --all or at least one pattern must be provided")
        sys.exit(1)

    patterns = ["*"] if args.all else args.patterns
    redis = setup_data_redis_connection()
    deleted_count = 0

    for key in iter_matching_keys(redis, patterns):
        deleted_count += redis.delete(key)

    logger.info(f"{deleted_count} Redis data keys deleted")


if __name__ == "__main__":
    main()
