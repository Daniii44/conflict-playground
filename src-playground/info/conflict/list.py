#!/usr/bin/env python3

import argparse
import sys
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT_CORE

DEFAULT_LIMIT = 1_000_000

def escape_value(value: str):
    escaped = value.replace("\\", "\\\\")
    for char in " ,.<>{}[]\"':;!@#$%^&*()-+=~|/":
        escaped = escaped.replace(char, f"\\{char}")
    return escaped

def excape_values(values: list[str]):
    return [escape_value(value) for value in values]

def build_tag_query_clause(tag: str, values: list[str]):
    escaped_clauses = excape_values(values)

    if not escaped_clauses:
        return ""
    return f"@{tag}:{{{"|".join(escaped_clauses)}}}"

def build_query(query_clauses: list[str]):
    query = " ".join([query_clause for query_clause in query_clauses if query_clause != ""])
    
    if query == "":
        return "*"
    return query

def list_conflicts(repos: list[str] = list(), conflict_types: list[str] = list(), limit: int = DEFAULT_LIMIT):
    query_clauses = list()
    query_clauses.append(build_tag_query_clause("repo", repos))
    query_clauses.append(build_tag_query_clause("type", conflict_types))
    query = build_query(query_clauses)

    redis = setup_redis_connection()
    query = Query(query)
    query.paging(0, limit)
    query.return_fields("merge_commit_oid", "repo")

    result:Result = cast(
        Result,
        redis.ft(IDX_INFO_CONFLICT_CORE).search(query)
    )

    return [(doc.repo, doc.merge_commit_oid) for doc in result.docs]

def main():
    parser = argparse.ArgumentParser(description="Print a list of conflict SHA")
    parser.add_argument(
        "-r",
        "--repo",
        action="append",
        help="Name of the bare git repository",
    )
    parser.add_argument(
        "-t",
        "--conflict-type",
        action="append",
        help='Selects only conflicts of the selected type',
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Limit the amount of shas"
    )
    args = parser.parse_args()
    repos:list[str] = args.repo or []
    conflict_types:list[str] = args.conflict_type or []
    
    for (repo, merge_commit_oid) in list_conflicts(repos, conflict_types, args.limit):
        print(repo, merge_commit_oid)

if __name__ == "__main__":
    main()
