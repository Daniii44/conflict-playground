#!/usr/bin/env python3

import argparse
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT_CORE


def escape_value(value: str):
    escaped = value.replace("\\", "\\\\")
    for char in " ,.<>{}[]\"':;!@#$%^&*()-+=~|/":
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def main():
    parser = argparse.ArgumentParser(description="Count conflict merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    args = parser.parse_args()
    
    redis = setup_redis_connection()
    query = Query(f"@repo:{{{escape_value(args.git_repo_name)}}}").return_fields()
    result:Result = cast(
        Result,
        redis.ft(IDX_INFO_CONFLICT_CORE).search(query)
    )
    
    print(f"{result.total}")

if __name__ == "__main__":
    main()
