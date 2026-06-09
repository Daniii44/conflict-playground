#!/usr/bin/env python3

import argparse
import subprocess
import sys

from loguru import logger

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection
from common.resolution_models import ConflictResolution, resolution_key_parts


def restore_resolution(redis, resolution_key: str) -> str:
    resolution_data = redis.json().get(resolution_key)
    if not resolution_data:
        raise RuntimeError(f"No resolution found at {resolution_key}")

    resolution = ConflictResolution.model_validate(resolution_data)
    proposed_resolution = resolution.proposed_resolution
    if proposed_resolution is None:
        raise RuntimeError(f"Resolution {resolution_key} has no proposed_resolution")
    if proposed_resolution.git_archive is None:
        error = proposed_resolution.error or "resolution has no archived .git repository"
        raise RuntimeError(f"Resolution {resolution_key} cannot be restored: {error}")

    playground_name, _ = resolution_key_parts(resolution_key)
    result = subprocess.run(
        ["playground-restore", playground_name],
        input=proposed_resolution.git_archive,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Could not restore resolution archive: {error}")

    return playground_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a saved conflict resolution playground by Redis key")
    parser.add_argument("resolution_key", help=f"Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    args = parser.parse_args()

    redis = setup_redis_connection()
    try:
        playground_name = restore_resolution(redis, args.resolution_key)
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    print(playground_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
