#!/usr/bin/env python3

import argparse
import json
import os
from pydoc import doc
import subprocess
import sys
from typing import cast
from redis.commands.search.query import Query
from redis.commands.search.result import Result
from common.redis_util import setup_redis_connection, IDX_INFO_CONFLICT_CORE
from rich.console import Console
from rich.table import Table


def print_pretty_info(doc):
    console = Console()
    table = Table(title=f"Conflict Commit Info for SHA {doc.id}")
    table.add_column("Field", style="magenta")
    table.add_column("Value", style="green")

    for field, value in doc.__dict__.items():
        if field not in ['payload', 'id']:
            table.add_row(field, str(value))
    
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Print the SHA of the N-th conflict merge commit from a bare git repository")
    parser.add_argument("sha", help="SHA of the commit to print")
    args = parser.parse_args()
    
    redis = setup_redis_connection()
    query = Query(f"@sha:{{{args.sha}}}")
    query.paging(0, 1)

    result:Result = cast(
        Result,
        redis.ft(IDX_INFO_CONFLICT_CORE).search(query)
    )

    if result.total == 0:
        print(f"No results found for sha {args.sha}", file=sys.stderr)
        exit(1)

    conflict_info = result.docs[0]
    print_pretty_info(conflict_info)
    print()

    repo_dir = os.environ.get("CACHES", "../../caches") + f"/repos/{conflict_info.repo}.git"
    command = f"git --git-dir={repo_dir} show {args.sha}"
    show_result = subprocess.run(
        command.split(),
        capture_output=True,
        text=True,
        check=True
    )
    print(f"Git show output for commit {args.sha}:\n{show_result.stdout}")

if __name__ == "__main__":
    main()
