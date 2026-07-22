#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import redis
import requests
from tqdm import tqdm

from common.redis_util import EVALUATION_MERGE_PREFIX, RESOLUTION_CONFLICT_PREFIX, RUNTIME_ACTIVE_PLAYGROUND_PREFIX
from common.schesch import parse_schesch_playground_name
from state.clickhouse.schema import (
    CLICKHOUSE_DB,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_TABLE,
    CLICKHOUSE_URL,
    CLICKHOUSE_USER,
    create_table,
)


REDIS_PREFIX = ""
INFO_CONFLICT_PREFIX = "info:conflict:"
DATASET_TILT_PREFIX = "dataset:tilt:"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S.%fZ"

r = redis.Redis(host="redis", port=6379, decode_responses=True)


def iter_keys(prefix: str):
    for key in r.scan_iter(match=f"{prefix}*"):
        yield key


def fetch_json(key: str):
    # RedisJSON GET
    return r.json().get(key, "$")

def normalize_timestamp(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def dict_path(data: object, *path: str) -> object | None:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


@dataclass(frozen=True)
class ConflictColumns:
    conflict_identifier: str = ""
    repo: str = ""
    merge_hash: str = ""
    conflict_timestamp: str = ""


def repo_without_git_suffix(repo_name: str) -> str:
    return repo_name.removesuffix(".git")


def build_conflict_columns(
    repo_name: str,
    merge_hash: str,
    conflict_timestamp: str = "",
) -> ConflictColumns:
    repo = repo_without_git_suffix(repo_name)
    conflict_identifier = f"{repo_name}-{merge_hash}"
    if conflict_timestamp:
        conflict_identifier = f"{conflict_identifier}:{conflict_timestamp}"
    return ConflictColumns(
        conflict_identifier=conflict_identifier,
        repo=repo,
        merge_hash=merge_hash,
        conflict_timestamp=conflict_timestamp,
    )


def conflict_columns_from_resolution_key(resolution_key: str) -> ConflictColumns | None:
    suffix = resolution_key.removeprefix(RESOLUTION_CONFLICT_PREFIX)
    if suffix == resolution_key or "-" not in suffix or ":" not in suffix:
        return None
    playground_name, _, conflict_timestamp = suffix.rpartition(":")
    repo_name, _, merge_hash = playground_name.rpartition("-")
    if not repo_name or not merge_hash or not conflict_timestamp:
        return None
    return build_conflict_columns(repo_name, merge_hash, conflict_timestamp)


def conflict_columns_from_evaluation_key(evaluation_key: str) -> ConflictColumns | None:
    suffix = evaluation_key.removeprefix(EVALUATION_MERGE_PREFIX)
    if suffix == evaluation_key:
        return None
    _analysis_name, separator, resolution_postfix = suffix.partition(":")
    if not separator or not resolution_postfix:
        return None
    return conflict_columns_from_resolution_key(
        f"{RESOLUTION_CONFLICT_PREFIX}{resolution_postfix}"
    )


def conflict_columns_from_info_key(info_key: str) -> ConflictColumns | None:
    suffix = info_key.removeprefix(INFO_CONFLICT_PREFIX)
    if suffix == info_key:
        return None
    _analysis_name, separator, repo_and_merge = suffix.partition(":")
    if not separator or ":" not in repo_and_merge:
        return None
    repo_name, _, merge_sha = repo_and_merge.rpartition(":")
    if not repo_name or not merge_sha:
        return None
    return build_conflict_columns(repo_name, merge_sha)


def conflict_columns_from_dataset_key(dataset_key: str) -> ConflictColumns | None:
    suffix = dataset_key.removeprefix(DATASET_TILT_PREFIX)
    if suffix == dataset_key or ":" not in suffix:
        return None
    repo_name, _, merge_sha = suffix.rpartition(":")
    if not repo_name or not merge_sha:
        return None
    return build_conflict_columns(repo_name, merge_sha)


def conflict_columns_from_runtime_key(runtime_key: str, content: object) -> ConflictColumns | None:
    playground_name = runtime_key.removeprefix(RUNTIME_ACTIVE_PLAYGROUND_PREFIX)
    if playground_name == runtime_key:
        return None
    try:
        repo_name, merge_sha = parse_schesch_playground_name(playground_name)
    except RuntimeError:
        return None

    timestamp = dict_path(content, "configuration", "resolution_start")
    if not isinstance(timestamp, str):
        return build_conflict_columns(repo_name, merge_sha)

    normalized = normalize_timestamp(timestamp)
    if normalized is None:
        return build_conflict_columns(repo_name, merge_sha)
    return build_conflict_columns(repo_name, merge_sha, normalized)


def extract_conflict_columns(key: str, content: object) -> ConflictColumns:
    """Map known Redis key families to canonical conflict export columns.

    The exporter uses the Redis key syntax as the source of truth:
    - resolution keys already embed ``owner/repo.git-mergehash:timestamp``
    - evaluation keys wrap a resolution key as ``evaluation:merge:<analysis>:...``
    - runtime active-playground keys embed ``owner/repo.git-mergehash`` and take
      ``configuration.resolution_start`` from the JSON payload as the timestamp
    - info and dataset keys only embed ``owner/repo.git:mergehash``, so their
      exported timestamp column stays empty and their identifier is the
      timestamp-less ``owner/repo.git-mergehash``

    For unknown key families, the exporter falls back to common JSON fields when
    available and otherwise leaves the derived columns empty.
    """
    if key.startswith(RESOLUTION_CONFLICT_PREFIX):
        columns = conflict_columns_from_resolution_key(key)
        if columns is not None:
            return columns
    if key.startswith(EVALUATION_MERGE_PREFIX):
        columns = conflict_columns_from_evaluation_key(key)
        if columns is not None:
            return columns
    if key.startswith(RUNTIME_ACTIVE_PLAYGROUND_PREFIX):
        columns = conflict_columns_from_runtime_key(key, content)
        if columns is not None:
            return columns
    if key.startswith(INFO_CONFLICT_PREFIX):
        columns = conflict_columns_from_info_key(key)
        if columns is not None:
            return columns
    if key.startswith(DATASET_TILT_PREFIX):
        columns = conflict_columns_from_dataset_key(key)
        if columns is not None:
            return columns

    resolution_key = dict_path(content, "resolution_key")
    if isinstance(resolution_key, str):
        columns = conflict_columns_from_resolution_key(resolution_key)
        if columns is not None:
            return columns

    repo_name = dict_path(content, "repo")
    merge_sha = dict_path(content, "merge_commit_oid")
    if isinstance(repo_name, str) and isinstance(merge_sha, str):
        return build_conflict_columns(repo_name, merge_sha)
    return ConflictColumns()


def extract_conflict_identifier(key: str, content: object) -> str:
    return extract_conflict_columns(key, content).conflict_identifier

def remove_duplicates():
    query = f"OPTIMIZE TABLE {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} FINAL"

    resp = requests.post(
        f"{CLICKHOUSE_URL}/?query={query}",
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    resp.raise_for_status()

def insert_clickhouse(rows):
    encoded_rows = []
    for key, content in rows:
        decoded_content = json.loads(content)
        conflict_columns = extract_conflict_columns(key, decoded_content)
        encoded_rows.append(
            json.dumps(
                {
                    "key": key,
                    "conflict_identifier": conflict_columns.conflict_identifier,
                    "repo": conflict_columns.repo,
                    "merge_hash": conflict_columns.merge_hash,
                    "conflict_timestamp": conflict_columns.conflict_timestamp,
                    "content": decoded_content,
                },
                ensure_ascii=False,
            )
        )
    data = "\n".join(encoded_rows)

    resp = requests.post(
        f"{CLICKHOUSE_URL}/?query="
        f"INSERT INTO {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} "
        f"FORMAT JSONEachRow",
        data=data.encode("utf-8"),
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
        headers={
            "Content-Type": "application/x-ndjson",
        },
    )

    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(
        description="Export RedisJSON records into ClickHouse.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""conflict_identifier extraction:
  resolution:conflict:<owner/repo.git-mergehash>:<timestamp>
    -> conflict_identifier=owner/repo.git-mergehash:timestamp
       repo=owner/repo merge_hash=mergehash conflict_timestamp=timestamp
  evaluation:merge:<analysis>:<owner/repo.git-mergehash>:<timestamp>
    -> same as resolution
  runtime:active_playground:<owner/repo.git-mergehash>
    -> same repo/merge, timestamp from configuration.resolution_start
  info:conflict:<analysis>:<owner/repo.git>:<mergehash>
    -> repo=owner/repo merge_hash=mergehash conflict_timestamp=''

Some Redis key families identify only the conflict, not one timestamped attempt.
Those rows export an empty conflict_timestamp string.
""",
    )
    parser.add_argument("--prefix", default=REDIS_PREFIX, help="Redis key prefix to export")
    args = parser.parse_args()

    create_table()

    batch = []
    BATCH_SIZE = 500

    for key in tqdm(iter_keys(args.prefix), desc="Exporting Redis keys", unit="key"):
        json_obj = fetch_json(key)

        # RedisJSON returns nested structure like [ {...} ]
        if isinstance(json_obj, list) and len(json_obj) == 1:
            json_obj = json_obj[0]

        batch.append((key, json.dumps(json_obj)))

        if len(batch) >= BATCH_SIZE:
            insert_clickhouse(batch)
            batch.clear()

    if batch:
        insert_clickhouse(batch)

    remove_duplicates()


if __name__ == "__main__":
    main()
