#!/usr/bin/env python3

import argparse
import sys

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def list_resolution_keys(redis) -> list[str]:
    return sorted(normalize_key(key) for key in redis.scan_iter(match=f"{RESOLUTION_CONFLICT_PREFIX}*"))


def prune_resolution(redis, key: str | None = None, prune_all: bool = False) -> list[str]:
    if prune_all:
        keys = list_resolution_keys(redis)
    elif key:
        keys = [key]
    else:
        raise RuntimeError("Specify a resolution key or --all")

    if keys:
        redis.delete(*keys)

    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove saved conflict resolution Redis keys")
    parser.add_argument("-a", "--all", "-all", action="store_true", dest="prune_all", help="Remove all saved resolutions")
    parser.add_argument("key", nargs="?", help=f"Resolution Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    args = parser.parse_args()

    if args.prune_all and args.key:
        parser.error("Specify either a key or --all, not both")

    try:
        deleted_keys = prune_resolution(redis=setup_redis_connection(), key=args.key, prune_all=args.prune_all)
    except RuntimeError as error:
        parser.error(str(error))
        return 2

    for key in deleted_keys:
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
