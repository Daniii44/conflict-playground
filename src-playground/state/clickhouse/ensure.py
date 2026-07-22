#!/usr/bin/env python3

import argparse

from state.clickhouse.schema import create_table, create_views, drop_table, drop_views


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Drop the ClickHouse Redis export table and recreate it with the "
            "schema defined in code."
        )
    )
    parser.parse_args()

    drop_views()
    drop_table()
    create_table()
    create_views()


if __name__ == "__main__":
    main()
