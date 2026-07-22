from __future__ import annotations

from pathlib import Path
import sys

import requests


CLICKHOUSE_URL = "http://clickhouse:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASSWORD = "dev-dynha9-fenvYc-daqmeh"
CLICKHOUSE_TABLE = "redis_json"
CLICKHOUSE_OVERVIEW_BASE_VIEW = "redis_json_overview_base"
CLICKHOUSE_OVERVIEW_CHART_VIEW = "redis_json_overview_chart"
CLICKHOUSE_OVERVIEW_TABLE_VIEW = "redis_json_overview_table"

ASSETS_SQL_DIR = (
    Path(__file__).resolve().parents[3]
    / "assets"
    / "playground"
    / "sql"
)
CONTAINER_SQL_DIR = Path("/root/sql")


def run_query(query: str) -> requests.Response:
    response = requests.post(
        CLICKHOUSE_URL,
        data=query.encode("utf-8"),
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if not response.ok:
        body = response.text.strip()
        if body:
            print(body, file=sys.stderr)
    response.raise_for_status()
    return response


def load_sql_asset(filename: str) -> str:
    for base_dir in (CONTAINER_SQL_DIR, ASSETS_SQL_DIR):
        path = base_dir / filename
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"Could not find SQL asset {filename!r} in {CONTAINER_SQL_DIR} or {ASSETS_SQL_DIR}"
    )


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


def overview_base_view_query() -> str:
    return load_sql_asset("overview-base.sql")


def overview_chart_view_query() -> str:
    return load_sql_asset("overview-chart.sql")


def overview_table_view_query() -> str:
    return load_sql_asset("overview-table.sql")


def drop_table_query() -> str:
    return f"DROP TABLE IF EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE}"


def drop_view_query(view_name: str) -> str:
    return f"DROP VIEW IF EXISTS {CLICKHOUSE_DB}.{view_name}"


def create_table() -> None:
    run_query(create_table_query())


def drop_table() -> None:
    run_query(drop_table_query())


def create_views() -> None:
    for query in (
        overview_base_view_query(),
        overview_chart_view_query(),
        overview_table_view_query(),
    ):
        run_query(query)


def drop_views() -> None:
    for view_name in (
        CLICKHOUSE_OVERVIEW_TABLE_VIEW,
        CLICKHOUSE_OVERVIEW_CHART_VIEW,
        CLICKHOUSE_OVERVIEW_BASE_VIEW,
    ):
        run_query(drop_view_query(view_name))
