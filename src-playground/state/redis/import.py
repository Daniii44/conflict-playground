#!/usr/bin/env python3

import argparse
import json

from loguru import logger

from state.redis._data import SEMANTIC_SAVE_NAME, resolve_save_path, restore_key, setup_data_redis_connection


def main():
    parser = argparse.ArgumentParser(
        description="Import Redis data keys from an NDJSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""example:
  state-redis-import submodule-info-v1

Semantic playbook saves use: {SEMANTIC_SAVE_NAME}
Use state-redis-sync <playbook> to load the latest semantic set for a playbook.
""",
    )
    parser.add_argument("save_name", help="Name of the save file under $STORES/redis-saves")
    args = parser.parse_args()

    redis = setup_data_redis_connection()
    input_path = resolve_save_path(args.save_name)
    imported_count = 0

    with open(input_path, "r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
                restore_key(redis, record)
            except Exception as error:
                logger.error(f"Failed to import {input_path}:{line_number}: {error}")
                raise

            imported_count += 1

    logger.info(f"{imported_count} Redis data keys imported from {input_path}")


if __name__ == "__main__":
    main()
