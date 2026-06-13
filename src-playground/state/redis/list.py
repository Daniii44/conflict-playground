#!/usr/bin/env python3

import argparse

from state.redis._data import REDIS_SAVE_SUFFIX, resolve_save_dir


def main():
    parser = argparse.ArgumentParser(description="List Redis save files")
    parser.parse_args()

    save_dir = resolve_save_dir()
    if not save_dir.exists():
        return

    for save_file in sorted(save_dir.glob(f"*{REDIS_SAVE_SUFFIX}")):
        print(save_file.name.removesuffix(REDIS_SAVE_SUFFIX))


if __name__ == "__main__":
    main()
