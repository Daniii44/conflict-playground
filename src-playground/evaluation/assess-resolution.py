#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection
from evaluation.sync import AVAILABLE_ANALYSES, evaluate_resolution_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one saved conflict resolution by Redis key")
    parser.add_argument("resolution_key", help=f"Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    parser.add_argument("-a", "--analysis", action="append", help="Name of an analysis to run")
    parser.add_argument("--all-analysis", action="store_true", help="Run all available analyses")
    args = parser.parse_args()

    redis = setup_redis_connection()
    if args.all_analysis:
        analyses = list(AVAILABLE_ANALYSES)
    else:
        analyses = args.analysis or ["core"]

    try:
        evaluation_keys = evaluate_resolution_key(redis, args.resolution_key, analyses=analyses)
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    for evaluation_key in evaluation_keys:
        logger.info("Stored evaluation at {}", evaluation_key)
        print(evaluation_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
