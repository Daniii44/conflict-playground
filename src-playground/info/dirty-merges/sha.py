#!/usr/bin/env python3

import argparse
import sys
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection


def main():
    parser = argparse.ArgumentParser(description="Collect dirty merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    parser.add_argument("index", help="Index of the SHA to print", type=int)
    args = parser.parse_args()
    
    redis = setup_redis_connection()
    query = Query(f"@repo:{{{args.git_repo_name.replace('-', '\\-')}}}")
    query.paging(args.index, 1)
    query.return_fields("sha", "conflict_count")
    query.sort_by("sha") # Ensure deterministic order (otherwise paging might be inconsistent)

    result:Result = cast(
        Result,
        redis.ft("idx:conflicts:info").search(query)
    )

    if result.total == 0:
        print(f"No results found for repo {args.git_repo_name}", file=sys.stderr)
        exit(1)
    if result.total <= args.index:
        print(f"Only found {result.total} results for repo {args.git_repo_name}, less than equal requested index {args.index}", file=sys.stderr)
        exit(1)

    for doc in result.docs:
        print(doc.sha)

if __name__ == "__main__":
    main()
