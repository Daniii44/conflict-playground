#!/usr/bin/env python3

import argparse
import sys
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT



def main():
    parser = argparse.ArgumentParser(description="Clean conflict info")
    parser.add_argument("git_repo_name", nargs="?", help="Name of the bare git repository")
    parser.add_argument("-a", "--all", action="store_true", help="Force clean of allconflict info")
    args = parser.parse_args()

    if not args.all and not args.git_repo_name:
        print("Either --all or git_repo_name must be provided")
        sys.exit(1)
    
    redis = setup_redis_connection()
    deleted_count = 0
    if args.all:
        for key in redis.scan_iter(match="info:conflict:*"):
            redis.delete(key)
            print(key)
            deleted_count += 1
    else:
        query = Query(f"@repo:{{{args.git_repo_name.replace('-', '\\-')}}}").return_fields().paging(0, 1000000)
        result:Result = cast(
            Result,
            redis.ft(IDX_INFO_CONFLICT).search(query)
        )
        for doc in result.docs:
            redis.delete(doc.id)
            deleted_count += 1
    
    print(f"{deleted_count} conflict info entries deleted")

if __name__ == "__main__":
    main()
