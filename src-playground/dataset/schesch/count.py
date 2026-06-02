#!/usr/bin/env python3

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True)
class ScheschMergeAnalysisCounts:
    distinct_repos: int
    distinct_merges: int


def default_merge_analysis_path() -> Path:
    datasets_env = os.environ.get("DATASETS")
    if datasets_env:
        return Path(datasets_env) / "schesch" / "merge_analysis"

    local_data = Path.cwd() / "data" / "datasets"
    if local_data.exists():
        return local_data / "schesch" / "merge_analysis"

    return Path("/root/datasets/schesch/merge_analysis")


def parse_merge_analysis_key(key: str) -> tuple[str, str] | None:
    parts = key.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def is_qualifying_merge(value) -> bool:
    if not isinstance(value, dict):
        return False

    num_diff_files = value.get("num_diff_files")
    num_diff_hunks = value.get("num_diff_hunks")

    return (
        value.get("diff contains java file") is True
        and value.get("test merge") is True
        and value.get("parents pass") is True
        and value.get("left parent test result") == "Tests_passed"
        and value.get("right parent test result") == "Tests_passed"
        and isinstance(num_diff_files, int)
        and num_diff_files < 1000
        and isinstance(num_diff_hunks, int)
    )


def iter_json_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [dirname for dirname in dirnames if not dirname.startswith(".")]
        for filename in filenames:
            if filename.endswith(".json"):
                yield Path(dirpath) / filename


def repo_name_for_file(root: Path, json_file: Path) -> str:
    relative = json_file.relative_to(root)
    return relative.with_suffix("").as_posix()


def count_merge_analysis(root: Path) -> ScheschMergeAnalysisCounts:
    repos_with_qualifying_merges: set[str] = set()
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

        repo_had_qualifying_merge = False
        for key, value in payload.items():
            merge_pair = parse_merge_analysis_key(key)
            if merge_pair is None:
                logger.warning("Skipping malformed merge analysis key {} in {}", key, json_file)
                continue

            if not is_qualifying_merge(value):
                continue

            left_sha, right_sha = merge_pair
            distinct_merges.add((repo, left_sha, right_sha))
            repo_had_qualifying_merge = True

        if repo_had_qualifying_merge:
            repos_with_qualifying_merges.add(repo)

    return ScheschMergeAnalysisCounts(
        distinct_repos=len(repos_with_qualifying_merges),
        distinct_merges=len(distinct_merges),
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Count distinct repositories and merge pairs in the Schesch merge_analysis "
            "dataset that have a Java diff and passing parent tests."
        )
    )
    parser.add_argument(
        "--merge-analysis",
        type=Path,
        default=default_merge_analysis_path(),
        help="Path to data/datasets/schesch/merge_analysis.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print counts as a JSON object.",
    )
    args = parser.parse_args()

    root = args.merge_analysis
    if not root.is_dir():
        parser.error(f"merge_analysis directory does not exist: {root}")

    counts = count_merge_analysis(root)
    if args.json:
        print(json.dumps(counts.__dict__, sort_keys=True))
        return

    print(f"distinct_repos {counts.distinct_repos}")
    print(f"distinct_merges {counts.distinct_merges}")


if __name__ == "__main__":
    main()
