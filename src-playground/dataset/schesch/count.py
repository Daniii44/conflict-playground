#!/usr/bin/env python3

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True)
class ScheschMergeTimingCounts:
    distinct_repos: int
    distinct_merges: int


def default_merge_timing_results_path() -> Path:
    datasets_env = os.environ.get("DATASETS")
    if datasets_env:
        return Path(datasets_env) / "schesch" / "merge_timing_results"

    local_data = Path.cwd() / "data" / "datasets"
    if local_data.exists():
        return local_data / "schesch" / "merge_timing_results"

    return Path("/root/datasets/schesch/merge_timing_results")


def parse_merge_timing_key(key: str) -> tuple[str, str] | None:
    parts = key.split("-", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        return None
    return parts[0], parts[1]


def iter_json_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [dirname for dirname in dirnames if not dirname.startswith(".")]
        for filename in filenames:
            if filename.endswith(".json"):
                yield Path(dirpath) / filename


def repo_name_for_file(root: Path, json_file: Path) -> str:
    relative = json_file.relative_to(root)
    return relative.with_suffix("").as_posix()


def count_merge_timing_results(root: Path) -> ScheschMergeTimingCounts:
    repos_with_timings: set[str] = set()
    distinct_merges: set[tuple[str, str, str]] = set()

    for json_file in iter_json_files(root):
        repo = repo_name_for_file(root, json_file)

        try:
            with json_file.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as error:
            logger.warning("Skipping invalid JSON file {}: {}", json_file, error)
            continue

        if not isinstance(payload, dict):
            logger.warning("Skipping non-object JSON file {}", json_file)
            continue

        repo_had_timing = False
        for key in payload:
            merge_pair = parse_merge_timing_key(key)
            if merge_pair is None:
                logger.warning("Skipping malformed merge timing key {} in {}", key, json_file)
                continue

            left_sha, right_sha = merge_pair
            distinct_merges.add((repo, left_sha, right_sha))
            repo_had_timing = True

        if repo_had_timing:
            repos_with_timings.add(repo)

    return ScheschMergeTimingCounts(
        distinct_repos=len(repos_with_timings),
        distinct_merges=len(distinct_merges),
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Count distinct repositories and merge pairs in the Schesch "
            "merge_timing_results dataset."
        )
    )
    parser.add_argument(
        "--merge-timing-results",
        type=Path,
        default=default_merge_timing_results_path(),
        help="Path to data/datasets/schesch/merge_timing_results.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print counts as a JSON object.",
    )
    args = parser.parse_args()

    root = args.merge_timing_results
    if not root.is_dir():
        parser.error(f"merge_timing_results directory does not exist: {root}")

    counts = count_merge_timing_results(root)
    if args.json:
        print(json.dumps(counts.__dict__, sort_keys=True))
        return

    print(f"distinct_repos {counts.distinct_repos}")
    print(f"distinct_merges {counts.distinct_merges}")


if __name__ == "__main__":
    main()
