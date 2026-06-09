#!/usr/bin/env python3

import argparse

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def list_resolution_keys(redis) -> list[str]:
    return sorted(normalize_key(key) for key in redis.scan_iter(match=f"{RESOLUTION_CONFLICT_PREFIX}*"))


def main() -> None:
    parser = argparse.ArgumentParser(description="List saved conflict resolution Redis keys")
    parser.parse_args()

    redis = setup_redis_connection()
    for key in list_resolution_keys(redis):
        print(key)


if __name__ == "__main__":
    main()
