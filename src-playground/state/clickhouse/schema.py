from __future__ import annotations

import requests


CLICKHOUSE_URL = "http://clickhouse:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASSWORD = "dev-dynha9-fenvYc-daqmeh"
CLICKHOUSE_TABLE = "redis_json"


def run_query(query: str) -> requests.Response:
    response = requests.post(
        f"{CLICKHOUSE_URL}/?query={query}",
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    response.raise_for_status()
    return response


def create_table_query() -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} (
        key String,
        conflict_identifier String,
        repo String,
        merge_hash String,
        conflict_timestamp String,
        content JSON,
        INDEX idx_conflict_identifier conflict_identifier TYPE bloom_filter GRANULARITY 1,
        INDEX idx_repo repo TYPE bloom_filter GRANULARITY 1,
        INDEX idx_merge_hash merge_hash TYPE bloom_filter GRANULARITY 1,
        INDEX idx_conflict_timestamp conflict_timestamp TYPE bloom_filter GRANULARITY 1
    )
    ENGINE = ReplacingMergeTree
    ORDER BY (repo, merge_hash, conflict_timestamp, key)
    """


def drop_table_query() -> str:
    return f"DROP TABLE IF EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE}"


def create_table() -> None:
    run_query(create_table_query())


def drop_table() -> None:
    run_query(drop_table_query())
