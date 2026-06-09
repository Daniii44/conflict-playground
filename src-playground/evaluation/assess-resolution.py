#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection
from evaluation.sync import evaluate_resolution_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one saved conflict resolution by Redis key")
    parser.add_argument("resolution_key", help=f"Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    args = parser.parse_args()

    redis = setup_redis_connection()
    try:
        evaluation_key = evaluate_resolution_key(redis, args.resolution_key)
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    logger.info("Stored evaluation at {}", evaluation_key)
    print(evaluation_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
