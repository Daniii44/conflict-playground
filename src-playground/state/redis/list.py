#!/usr/bin/env python3

import argparse
from datetime import datetime

from state.redis._data import REDIS_SAVE_SUFFIX, SEMANTIC_SAVE_NAME, resolve_save_dir


def format_modified_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def format_save_file(save_file) -> str:
    stat = save_file.stat()
    name = save_file.name.removesuffix(REDIS_SAVE_SUFFIX)
    modified = format_modified_timestamp(stat.st_mtime)
    return f"{name}\t{stat.st_size}\t{modified}"


def main():
    parser = argparse.ArgumentParser(
        description="List Redis save files",
        epilog=(
            f"Semantic playbook saves use: {SEMANTIC_SAVE_NAME}. "
            "Saves starting with _ are listed here but ignored by state sync."
        ),
    )
    parser.parse_args()

    save_dir = resolve_save_dir()
    if not save_dir.exists():
        return

    print("name\tsize_bytes\tmodified")
    for save_file in sorted(save_dir.glob(f"*{REDIS_SAVE_SUFFIX}")):
        print(format_save_file(save_file))


if __name__ == "__main__":
    main()
