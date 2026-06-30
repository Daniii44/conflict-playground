#!/usr/bin/env python3

import argparse
import subprocess
import sys

from loguru import logger


def list_available_analyses() -> list[str]:
    result = subprocess.run(
        ["info-conflict-sync", "--list-analyses"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_repos(playbook: str) -> list[str]:
    result = subprocess.run(
        ["playbook-repos", playbook],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def parse_args(available_analyses: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync conflict info for repositories referenced by a playbook",
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="default",
        help="Playbook name, defaults to default",
    )
    parser.add_argument(
        "-a",
        "--analysis",
        action="append",
        choices=available_analyses,
        help="Analysis to run. Can be provided multiple times. Defaults to all analyses.",
    )
    parser.add_argument(
        "--all-analysis",
        action="store_true",
        help="Run all available analyses. This is the default.",
    )
    parser.add_argument(
        "--list-analyses",
        action="store_true",
        help="List all available analyses and exit",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of worker threads to use per conflict analysis repo",
    )
    return parser.parse_args()


def main() -> int:
    try:
        available_analyses = list_available_analyses()
    except subprocess.CalledProcessError as error:
        logger.error("Failed to list available analyses")
        return error.returncode

    args = parse_args(available_analyses)

    if args.list_analyses:
        for analysis in available_analyses:
            print(analysis)
        return 0

    if args.all_analysis and args.analysis:
        logger.error("Use either --all-analysis or --analysis, not both")
        return 1

    if args.max_workers is not None and args.max_workers < 1:
        logger.error("--max-workers must be at least 1")
        return 1

    try:
        repos = collect_repos(args.playbook)
    except subprocess.CalledProcessError as error:
        logger.error("Failed to collect repositories for playbook {}", args.playbook)
        return error.returncode

    analysis_args = ["--all-analysis"]
    if args.analysis:
        analysis_args = [
            value
            for analysis in args.analysis
            for value in ("--analysis", analysis)
        ]
    if args.max_workers is not None:
        analysis_args.extend(["--max-workers", str(args.max_workers)])
    analysis_args.extend(["--playbook", args.playbook])

    failed_repos = []
    for repo in repos:
        logger.info("Processing: {}", repo)
        try:
            run(["info-conflict-sync", *analysis_args, repo])
        except subprocess.CalledProcessError as error:
            failed_repos.append(repo)
            logger.error(
                "Failed to sync conflict info for {} with command: {}",
                repo,
                " ".join(error.cmd),
            )

    logger.info("Syncing with Clickhouse")
    try:
        run(["state-clickhouse-sync"])
    except subprocess.CalledProcessError as error:
        logger.error("Failed to sync ClickHouse with command: {}", " ".join(error.cmd))
        return error.returncode

    if failed_repos:
        logger.error("Done syncing info with {} failed repos", len(failed_repos))
        for repo in failed_repos:
            logger.error("Failed info repo: {}", repo)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
