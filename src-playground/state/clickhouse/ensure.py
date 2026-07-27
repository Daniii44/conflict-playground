#!/usr/bin/env python3

from __future__ import annotations

import argparse

from state.clickhouse.schema import create_table, create_views, drop_table, drop_views


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
        drop_views()
        create_views()
        return

    drop_views()
    drop_table()
    create_table()

    if not args.skip_views:
        create_views()


if __name__ == "__main__":
    main()
