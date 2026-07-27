#!/usr/bin/env python3

from __future__ import annotations

import argparse

from loguru import logger

from state.clickhouse.schema import (
    CLICKHOUSE_DB,
    CLICKHOUSE_OVERVIEW_BASE_VIEW,
    CLICKHOUSE_OVERVIEW_CHART_VIEW,
    CLICKHOUSE_OVERVIEW_TABLE_VIEW,
    CLICKHOUSE_TABLE,
    create_table,
    create_views,
    drop_table,
    drop_views,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Drop the ClickHouse Redis export table and recreate it with the "
            "schema defined in code."
        )
    )
    parser.add_argument(
        "--skip-views",
        action="store_true",
        help="Only rebuild the exported Redis table, leaving overview views for a later pass.",
    )
    parser.add_argument(
        "--views-only",
        action="store_true",
        help="Only rebuild the overview views without dropping the exported Redis table.",
    )
    args = parser.parse_args(argv)

    if args.skip_views and args.views_only:
        parser.error("--skip-views and --views-only cannot be used together")

    if args.views_only:
        logger.info(
            "Rebuilding ClickHouse overview views only: {}.{} (materialized), {}.{}, {}.{}",
            CLICKHOUSE_DB,
            CLICKHOUSE_OVERVIEW_BASE_VIEW,
            CLICKHOUSE_DB,
            CLICKHOUSE_OVERVIEW_CHART_VIEW,
            CLICKHOUSE_DB,
            CLICKHOUSE_OVERVIEW_TABLE_VIEW,
        )
        logger.info("Dropping existing ClickHouse overview views")
        drop_views()
        logger.info("Creating ClickHouse overview views")
        create_views()
        logger.info("Finished rebuilding ClickHouse overview views")
        return

    logger.info(
        "Rebuilding ClickHouse export schema for {}.{}",
        CLICKHOUSE_DB,
        CLICKHOUSE_TABLE,
    )
    logger.info("Dropping ClickHouse overview views before table rebuild")
    drop_views()
    logger.info("Dropping ClickHouse export table {}.{}", CLICKHOUSE_DB, CLICKHOUSE_TABLE)
    drop_table()
    logger.info("Creating ClickHouse export table {}.{}", CLICKHOUSE_DB, CLICKHOUSE_TABLE)
    create_table()

    if not args.skip_views:
        logger.info("Creating ClickHouse overview views")
        create_views()
        logger.info("Finished rebuilding ClickHouse export schema and overview views")
    else:
        logger.info("Skipped ClickHouse overview view rebuild; run with --views-only after export")


if __name__ == "__main__":
    main()
