#!/usr/bin/env python3

from info.redis._data import setup_data_redis_connection


def main():
    redis = setup_data_redis_connection()
    print(redis.dbsize())


if __name__ == "__main__":
    main()
