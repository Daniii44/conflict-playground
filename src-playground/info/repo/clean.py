#!/usr/bin/env python3

import argparse
import sys
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT_CORE



def main():
    redis = setup_redis_connection()
    deleted_count = 0
    
    for key in redis.scan_iter(match="info:repo:*"):
        redis.delete(key)
        deleted_count += 1
    
    print(f"{deleted_count} conflict info entries deleted")

if __name__ == "__main__":
    main()
