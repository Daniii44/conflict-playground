#!/usr/bin/env python3

import argparse
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection


def main():
    parser = argparse.ArgumentParser(description="Collect dirty merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    args = parser.parse_args()
    
    redis = setup_redis_connection()
    query = Query(f"@repo:{{{args.git_repo_name.replace('-', '\\-')}}}").return_fields()
    result:Result = cast(
        Result,
        redis.ft("idx:conflicts:info").search(query)
    )
    
    print(f"{result.total}")

if __name__ == "__main__":
    main()
