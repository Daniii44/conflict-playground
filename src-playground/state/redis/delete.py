#!/usr/bin/env python3

import argparse
import sys

from loguru import logger

from state.redis._data import resolve_save_path


def main():
    parser = argparse.ArgumentParser(description="Delete a Redis save file")
    parser.add_argument("save_name", help="Name of the save file under $STORES/redis-saves")
    args = parser.parse_args()

    save_path = resolve_save_path(args.save_name)
    if not save_path.exists():
        logger.error(f"Redis save does not exist: {args.save_name}")
        sys.exit(1)

    save_path.unlink()
    logger.info(f"Deleted Redis save {args.save_name}")


if __name__ == "__main__":
    main()
