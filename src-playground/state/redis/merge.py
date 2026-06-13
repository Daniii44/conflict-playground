#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

from loguru import logger

from state.redis._data import SEMANTIC_SAVE_NAME, resolve_save_path


def append_save_records(output, save_path: Path) -> int:
    record_count = 0
    with open(save_path, "r", encoding="utf-8") as input_file:
        for line in input_file:
            line = line.strip()
            if not line:
                continue

            output.write(line)
            output.write("\n")
            record_count += 1

    return record_count


def merge_save_files(save_file_1: str, save_file_2: str, merge_file: str) -> int:
    input_paths = [resolve_save_path(save_file_1), resolve_save_path(save_file_2)]
    output_path = resolve_save_path(merge_file)

    for input_path in input_paths:
        if not input_path.exists():
            raise FileNotFoundError(f"Redis save does not exist: {input_path.name}")

    if output_path in input_paths:
        raise ValueError("Merge output must be different from both input saves")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged_count = 0
    with open(output_path, "w", encoding="utf-8") as output:
        for input_path in input_paths:
            merged_count += append_save_records(output, input_path)

    return merged_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge two Redis save files into one NDJSON save",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""example:
  state-redis-merge submodule-info-v1 submodule-resolution-v1 submodule-state-v1

Semantic playbook saves use: {SEMANTIC_SAVE_NAME}
This command concatenates all records from both inputs and does not deduplicate keys.
""",
    )
    parser.add_argument("save_file_1", help="First save file under $STORES/redis-saves")
    parser.add_argument("save_file_2", help="Second save file under $STORES/redis-saves")
    parser.add_argument("merge_file", help="Output save file under $STORES/redis-saves")
    args = parser.parse_args()

    try:
        merged_count = merge_save_files(args.save_file_1, args.save_file_2, args.merge_file)
    except (FileNotFoundError, ValueError) as error:
        logger.error(str(error))
        return 1

    logger.info(f"{merged_count} Redis save records merged into {resolve_save_path(args.merge_file)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
