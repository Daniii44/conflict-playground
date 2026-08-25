#!/usr/bin/env python3

import os
import argparse
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from loguru import logger
from pydantic import BaseModel
from redis.commands.json.path import Path as RedisPath
from tqdm import tqdm

from common.git_util import capture_git
from common.playbook import load_playbook_data, resolve_playbook_path
from common.repo_cache import repo_cache_key
from common.redis_util import setup_redis_connection
from info.conflict.analysis.common import Analysis, AnalysisInput
from info.conflict.analysis.core_analysis import CoreAnalysis
from info.conflict.analysis.octopus_analysis import OctopusAnalysis
from info.conflict.analysis.schesch_analysis import ScheschInfoAnalysis
from info.conflict.analysis.tilt_analysis import TiltAnalysis
from info.conflict.analysis.modifydelete_analysis import ModifyDeleteInfoAnalysis
from playbook.playgrounds import playground_from_override, resolve_playground_merge_sha

# Script to collect all dirty merge commits in a bare git repository
# Usage: python collect-conflict.py <git-repo-name> [-f]

# FIXME
# fatal: unable to read tree (322895d3a525e8e6afc5b8ae049a73c41628b280)
# fatal: unable to read tree (26cfa9e41bbc6701fe9a751b7f91ffa48930c6d1
# fatal: unable to read tree (280ea2683eb11d4ecd722b12634b60d5bcd9a188)

# FIXME
# Stalls at 20892/20893 for git - maybe related with "unable to read tree"

exiting = False
AVAILABLE_ANALYSES: dict[str, type[Analysis]] = {
    "core": CoreAnalysis,
    "tilt": TiltAnalysis,
    "octopus": OctopusAnalysis,
    "schesch": ScheschInfoAnalysis,
    "modifydelete": ModifyDeleteInfoAnalysis,
}

def signal_handler(sig, frame):
    global exiting
    exiting = True

def already_analysed(analysis: Analysis, git_repo_name:str):
    any_exists = next(redis.scan_iter(match=f"{analysis.get_redis_result_prefix()}:{git_repo_name}*", count=10), False) is not False
    return any_exists

def collect_analyses(analyses: list[str], verbose: bool = False) -> list[Analysis]:
    def create_analysis(analysis: str):
        analysisType = AVAILABLE_ANALYSES.get(analysis)
        if analysisType is None:
            logger.error(f"No such analysis: {analysis}")
            logger.error(f"Available analyses: {', '.join(AVAILABLE_ANALYSES)}")
            sys.exit(-1)
        if analysisType is ScheschInfoAnalysis:
            return analysisType(analysis, stream_output=verbose)
        return analysisType(analysis)

    
    return [create_analysis(analysis) for analysis in analyses]

def collect_playbook_override_merge_shas(playbook_path: Path, git_repo_name: str) -> list[str] | None:
    data = load_playbook_data(playbook_path)
    sources = data.get("playbook", {}).get("sources") or []
    merge_shas: list[str] = []

    for source in sources:
        if not isinstance(source, dict) or not source.get("repo_url"):
            continue
        if repo_cache_key(source["repo_url"]) != git_repo_name:
            continue

        overrides = source.get("override_merge_shas") or []
        if not overrides:
            continue

        for override in overrides:
            playground = playground_from_override(git_repo_name, override)
            merge_shas.append(resolve_playground_merge_sha(playground))

    if not merge_shas:
        return None

    return list(dict.fromkeys(merge_shas))


def collect_analysis_candidates(
    git_dir: str,
    git_repo_name: str,
    override_merge_shas: list[str] | None = None,
) -> list[AnalysisInput]:
    if override_merge_shas:
        return [
            AnalysisInput(
                git_dir=git_dir,
                git_repo_name=git_repo_name,
                merge_commit_oid=merge_commit_oid,
            )
            for merge_commit_oid in override_merge_shas
        ]

    result = capture_git(
        f"--git-dir={git_dir}",
        "rev-list",
        "--merges",
        "HEAD",
        check=False,
    )
    if result.returncode != 0:
        logger.error("Error running git rev-list for {}: {}", git_repo_name, result.stderr.strip())
        sys.exit(1)

    rev_list = result.stdout.splitlines()
    return [AnalysisInput(
            git_dir=git_dir,
            git_repo_name=git_repo_name,
            merge_commit_oid=merge_commit_oid
        ) for merge_commit_oid in rev_list
    ]

def dispatch_analysis(analysis: Analysis, analysisInput: AnalysisInput):
    if exiting:
        return None

    try:
        return analysis.analyse(analysisInput)
    except Exception as e:
        logger.error("Analysis threw exception:", e)
    
    return None

def execute_analyses(analysis: Analysis, analysisInputs: list[AnalysisInput], verbose: bool, max_workers: int | None):
    max_workers = max_workers or os.cpu_count()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(dispatch_analysis, analysis, analysisInput) for analysisInput in analysisInputs]

        with tqdm(total=len(futures), desc=f"Analysing {analysis.get_analysis_name()}") as pbar:
            for future in as_completed(futures):
                if exiting:
                    sys.exit(0)

                result = future.result()
                if result is not None:
                    analysisInput:AnalysisInput = result[0]
                    analysisOutput:BaseModel = result[1]
                    key = f"{analysis.get_redis_result_prefix()}:{analysisInput.git_repo_name}:{analysisInput.merge_commit_oid}"
                    redis.json().set(key, RedisPath.root_path(), analysisOutput.model_dump())

                # Wrap as_completed in tqdm to get a live progress bar
                if not verbose:
                    pbar.update(1)

def main():
    parser = argparse.ArgumentParser(description="Collect conflict merge commits from a bare git repository")
    parser.add_argument("git_repo_name", nargs="?", help="Name of the bare git repository")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild even if merge commit list exists")
    parser.add_argument("-v", "--verbose", action="store_true", help="Display logs instead of progress bar")
    parser.add_argument(
        "-a",
        "--analysis",
        action="append",
        help="Name of an analysis to run",
    )
    parser.add_argument(
        "--all-analysis",
        action="store_true",
        help="Run all available analyses",
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
        help="Maximum number of worker threads to use for analysis (defaults to CPU count)",
    )
    parser.add_argument(
        "--playbook",
        help="Restrict candidates to override_merge_shas for this repo when the playbook provides them",
    )
    args = parser.parse_args()

    if args.list_analyses:
        for analysis in AVAILABLE_ANALYSES:
            print(analysis)
        sys.exit(0)

    if not args.git_repo_name:
        parser.error("the following arguments are required: git_repo_name")

    if args.max_workers is not None and args.max_workers < 1:
        parser.error("--max-workers must be at least 1")

    global redis
    redis = setup_redis_connection()

    signal.signal(signal.SIGINT, signal_handler)

    analyses:list[Analysis]
    if args.all_analysis:
        analyses = collect_analyses(list(AVAILABLE_ANALYSES), verbose=args.verbose)
    elif args.analysis:
        analyses = collect_analyses(args.analysis, verbose=args.verbose)
    else:
        analyses = collect_analyses(['core'], verbose=args.verbose)

    if not args.verbose:
        logger.disable("__main__");

    git_repo_name = args.git_repo_name
    force = args.force
    caches = Path(os.environ.get("CACHES", "../../caches"))
    git_dir = caches / "repos" / git_repo_name
    
    if not git_dir.is_dir():
        logger.error("Bare repository does not exist: {}", git_dir)
        sys.exit(1)

    override_merge_shas = None
    if args.playbook:
        playbooks_dir = Path(os.environ.get("PLAYBOOKS", "../../data/playbooks"))
        playbook_path = resolve_playbook_path(args.playbook, playbooks_dir)
        if not playbook_path.is_file():
            logger.error("Playbook does not exist: {}", playbook_path)
            sys.exit(1)
        override_merge_shas = collect_playbook_override_merge_shas(playbook_path, git_repo_name)
        if override_merge_shas:
            logger.info(
                "Restricting {} to {} override merge SHAs from {}",
                git_repo_name,
                len(override_merge_shas),
                playbook_path,
            )

    for analysis in analyses:
        if already_analysed(analysis, git_repo_name) and not force:
            print(f"Analysis data for repo {git_repo_name} of type {analysis.get_analysis_name()} already exists (use -f to force rebuild)")
            continue

        conflict_candidates = collect_analysis_candidates(str(git_dir), git_repo_name, override_merge_shas)
        execute_analyses(analysis, conflict_candidates, args.verbose, args.max_workers)

if __name__ == "__main__":
    main()
