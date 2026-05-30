#!/usr/bin/env python3

import argparse
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync repositories and conflict info for a playbook",
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        help="Playbook name or path. Defaults to each sync stage's default.",
    )
    parser.add_argument(
        "-a",
        "--analysis",
        action="append",
        help="Analysis to run during info sync. Can be provided multiple times.",
    )
    parser.add_argument(
        "--all-analysis",
        action="store_true",
        help="Run all available analyses during info sync.",
    )
    parser.add_argument(
        "--list-analyses",
        action="store_true",
        help="List available analyses and skip repository sync.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of worker threads to use per conflict analysis repo.",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def build_repo_args(args: argparse.Namespace) -> list[str]:
    if args.playbook is None:
        return []
    return [args.playbook]


def build_info_args(args: argparse.Namespace) -> list[str]:
    info_args: list[str] = []

    if args.playbook is not None:
        info_args.append(args.playbook)

    for analysis in args.analysis or []:
        info_args.extend(["--analysis", analysis])

    if args.all_analysis:
        info_args.append("--all-analysis")

    if args.list_analyses:
        info_args.append("--list-analyses")

    if args.max_workers is not None:
        info_args.extend(["--max-workers", str(args.max_workers)])

    return info_args


def main() -> int:
    args = parse_args()

    if args.max_workers is not None and args.max_workers < 1:
        print("sync: --max-workers must be at least 1", file=sys.stderr)
        return 2

    if args.all_analysis and args.analysis:
        print("sync: use either --all-analysis or --analysis, not both", file=sys.stderr)
        return 2

    try:
        if not args.list_analyses:
            print("Syncing Repositories")
            run(["repo-sync", *build_repo_args(args)])
            print()

        print("Syncing Info")
        run(["info-sync", *build_info_args(args)])
    except subprocess.CalledProcessError as error:
        return error.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
