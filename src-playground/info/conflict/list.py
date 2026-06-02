#!/usr/bin/env python3

import argparse
import sys
from dataclasses import dataclass
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT_CORE

DEFAULT_LIMIT = 1_000_000
INFO_CONFLICT_CORE_PREFIX = "info:conflict:core"


@dataclass(frozen=True)
class ConflictRecord:
    repo: str
    merge_commit_oid: str
    conflict_types: tuple[str, ...]

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

def _extract_conflict_types(data) -> tuple[str, ...]:
    if not isinstance(data, dict):
        return tuple()

    merge_result = data.get("merge_result")
    if not isinstance(merge_result, dict):
        return tuple()

    logical_conflicts = merge_result.get("logical_conflicts")
    if not isinstance(logical_conflicts, list):
        return tuple()

    conflict_types = []
    seen = set()
    for conflict in logical_conflicts:
        if not isinstance(conflict, dict):
            continue

        conflict_type = conflict.get("type")
        if not isinstance(conflict_type, str) or conflict_type in seen:
            continue

        seen.add(conflict_type)
        conflict_types.append(conflict_type)

    return tuple(conflict_types)


def list_conflict_records(
    repos: list[str] | None = None,
    conflict_types: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[ConflictRecord]:
    repos = repos or []
    conflict_types = conflict_types or []
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

    records = []
    for doc in result.docs:
        key = f"{INFO_CONFLICT_CORE_PREFIX}:{doc.repo}:{doc.merge_commit_oid}"
        records.append(
            ConflictRecord(
                repo=doc.repo,
                merge_commit_oid=doc.merge_commit_oid,
                conflict_types=_extract_conflict_types(redis.json().get(key)),
            )
        )

    return records


def list_conflicts(
    repos: list[str] | None = None,
    conflict_types: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
):
    return [
        (record.repo, record.merge_commit_oid)
        for record in list_conflict_records(repos, conflict_types, limit)
    ]

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
