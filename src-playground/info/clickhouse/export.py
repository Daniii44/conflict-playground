#!/usr/bin/env python3

import argparse
import json
import redis
import requests
from tqdm import tqdm

REDIS_PREFIX = "info:conflict:"
CLICKHOUSE_URL = "http://clickhouse:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASSWORD = "dev-dynha9-fenvYc-daqmeh"
CLICKHOUSE_TABLE = "redis_json"

r = redis.Redis(host="redis", port=6379, decode_responses=True)


def iter_keys(prefix: str):
    for key in r.scan_iter(match=f"{prefix}*"):
        yield key


def fetch_json(key: str):
    # RedisJSON GET
    return r.json().get(key, "$")

def ensure_table():
    query = f"""
    CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} (
        key String,
        content JSON
    )
    ENGINE = ReplacingMergeTree
    ORDER BY key
    """

    resp = requests.post(
        f"{CLICKHOUSE_URL}/?query={query}",
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    resp.raise_for_status()

def remove_duplicates():
    query = f"OPTIMIZE TABLE {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} FINAL"

    resp = requests.post(
        f"{CLICKHOUSE_URL}/?query={query}",
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASSWORD),
    )
    resp.raise_for_status()

def insert_clickhouse(rows):
    data = "\n".join(
        json.dumps(
            {
                "key": key,
                "content": json.loads(content),
            },
            ensure_ascii=False,
        )
        for key, content in rows
    )

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default=REDIS_PREFIX, help="Redis key prefix to export")
    args = parser.parse_args()

    ensure_table()

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