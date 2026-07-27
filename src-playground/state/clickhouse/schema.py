from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib import error, request

from loguru import logger


CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DB", "default")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "dev-dynha9-fenvYc-daqmeh")
CLICKHOUSE_TABLE = os.environ.get("CLICKHOUSE_TABLE", "redis_json")
CLICKHOUSE_OVERVIEW_BASE_VIEW = os.environ.get(
    "CLICKHOUSE_OVERVIEW_BASE_VIEW",
    "redis_json_overview_base",
)
CLICKHOUSE_OVERVIEW_CHART_VIEW = os.environ.get(
    "CLICKHOUSE_OVERVIEW_CHART_VIEW",
    "redis_json_overview_chart",
)
CLICKHOUSE_OVERVIEW_TABLE_VIEW = os.environ.get(
    "CLICKHOUSE_OVERVIEW_TABLE_VIEW",
    "redis_json_overview_table",
)

ASSETS_SQL_DIR = (
    Path(__file__).resolve().parents[3]
    / "assets"
    / "playground"
    / "sql"
)
CONTAINER_SQL_DIR = Path("/root/sql")


if not hasattr(error.HTTPError, "read"):
    def _http_error_read(self) -> bytes:
        if self.fp is None:
            return b""
        return self.fp.read()

    error.HTTPError.read = _http_error_read


def run_query(query: str) -> str:
    credentials = f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode("utf-8")
    encoded_credentials = base64.b64encode(credentials).decode("ascii")
    query_request = request.Request(
        CLICKHOUSE_URL,
        data=query.encode("utf-8"),
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )
    try:
        with request.urlopen(query_request) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        if body:
            logger.error("ClickHouse query failed: {}", body)
        raise


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


def drop_overview_base_query() -> str:
    return f"DROP TABLE IF EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_OVERVIEW_BASE_VIEW}"


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
    ):
        run_query(drop_view_query(view_name))
    run_query(drop_overview_base_query())
