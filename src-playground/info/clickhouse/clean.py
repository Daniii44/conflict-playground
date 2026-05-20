#!/usr/bin/env python3

import argparse
import requests

CLICKHOUSE_URL = "http://clickhouse:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASSWORD = "dev-dynha9-fenvYc-daqmeh"
CLICKHOUSE_TABLE = "redis_json"


def run_query(query: str):
	resp = requests.post(
		f"{CLICKHOUSE_URL}/?query={query}",
		auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
	)
	resp.raise_for_status()
	return resp


def delete_by_prefix(prefix: str):
	# Delete rows where `key` starts with the given prefix
	query = (
		f"ALTER TABLE {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} "
		f"DELETE WHERE startsWith(key, '{prefix}')"
	)
	print("Executing:", query)
	run_query(query)


def delete_all():
	# Delete all rows in the table
	query = f"ALTER TABLE {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} DELETE WHERE 1=1"
	print("Executing:", query)
	run_query(query)


def optimize_table():
	query = f"OPTIMIZE TABLE {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} FINAL"
	print("Optimizing table to finalize deletes")
	run_query(query)


def main():
	parser = argparse.ArgumentParser(description="Clean ClickHouse entries exported from Redis")
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument(
		"--all",
		action="store_true",
		help="Delete all rows from the ClickHouse table (use with caution)",
	)
	group.add_argument(
		"--prefix",
		help=f"Redis key prefix to delete",
	)

	args = parser.parse_args()

	if args.all:
		delete_all()
	else:
		# sanitize prefix for embedding in ClickHouse SQL
		prefix = args.prefix
		if prefix is None:
			parser.error("Either --all or --prefix must be provided")
		safe_prefix = prefix.replace("'", "\\'")
		delete_by_prefix(safe_prefix)

	optimize_table()


if __name__ == "__main__":
	main()

