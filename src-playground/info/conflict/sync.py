#!/usr/bin/env python3

from asyncio import futures
import signal

from loguru import logger
import os
import sys
import subprocess
import argparse
from redis.commands.json.path import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel
from tqdm import tqdm
import threading
import time
from common.redis_util import setup_redis_connection
from common.merge_tree import MergeResult, parse_merge_result, prune_auto_merged
from info.conflict.analysis.common import Analysis, AnalysisInput
from info.conflict.analysis.core_analysis import CoreAnalysis

# Script to collect all dirty merge commits in a bare git repository
# Usage: python collect-conflict.py <git-repo-name> [-f]

# FIXME
# fatal: unable to read tree (322895d3a525e8e6afc5b8ae049a73c41628b280)
# fatal: unable to read tree (26cfa9e41bbc6701fe9a751b7f91ffa48930c6d1
# fatal: unable to read tree (280ea2683eb11d4ecd722b12634b60d5bcd9a188)

# FIXME
# Stalls at 20892/20893 for git - maybe related with "unable to read tree"

exiting = False
def signal_handler(sig, frame):
    global exiting
    exiting = True

def already_analysed(analysis: Analysis, git_repo_name:str):
    any_exists = next(redis.scan_iter(match=f"{analysis.get_redis_result_prefix()}:{git_repo_name}*", count=10), False) is not False
    return any_exists

def collect_analyses(analyses: list[str]) -> list[Analysis]:
    def create_analysis(analysis: str):
        match analysis:
            case 'core': 
                analysisType = CoreAnalysis
            case _: 
                logger.error(f"No such analysis: {analysis}")
                sys.exit(-1)

        return analysisType(analysis)

    
    return [create_analysis(analysis) for analysis in analyses]

def collect_conflict_candidate_sha(git_dir: str) -> list[str]:
    rev_list_cmd = ["git", f"--git-dir={git_dir}", "rev-list", "--merges", "HEAD"]
    try:
        rev_list = subprocess.check_output(rev_list_cmd, text=True).splitlines()
    except subprocess.CalledProcessError as e:
        if e.returncode == -signal.SIGINT:
            global exiting
            exiting = True
        logger.error(f"Error running git rev-list: {e}")
        sys.exit(1)
    return rev_list

def collect_analysis_candidates(git_dir: str, git_repo_name: str) -> list[AnalysisInput]:
    rev_list_cmd = ["git", f"--git-dir={git_dir}", "rev-list", "--merges", "HEAD"]
    try:
        rev_list = subprocess.check_output(rev_list_cmd, text=True).splitlines()
    except subprocess.CalledProcessError as e:
        if e.returncode == -signal.SIGINT:
            global exiting
            exiting = True
        logger.error(f"Error running git rev-list: {e}")
        sys.exit(1)

    return [AnalysisInput(
            git_dir=git_dir,
            git_repo_name=git_repo_name,
            merge_commit_oid=merge_commit_oid
        ) for merge_commit_oid in rev_list
    ]

def dispatch_analysis(analysis: Analysis, analysisInput: AnalysisInput):
    if exiting:
        return None
    return analysis.analyse(analysisInput)

def execute_analyses(analysis: Analysis, analysisInputs: list[AnalysisInput], verbose: bool):
    max_workers = os.cpu_count()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(dispatch_analysis, analysis, analysisInput) for analysisInput in analysisInputs]

        with tqdm(total=len(futures), desc="Analysing Data") as pbar:
            for future in as_completed(futures):
                if exiting:
                    sys.exit(0)

                result = future.result()
                logger.info(result)
                if result is not None:
                    analysisInput:AnalysisInput = result[0]
                    analysisOutput:BaseModel = result[1]
                    key = f"{analysis.get_redis_result_prefix()}:{analysisInput.git_repo_name}{analysisInput.merge_commit_oid}"
                    logger.info(key)
                    redis.json().set(key, Path.root_path(), analysisOutput.model_dump())

                # Wrap as_completed in tqdm to get a live progress bar
                if not verbose:
                    pbar.update(1)

def main():
    parser = argparse.ArgumentParser(description="Collect conflict merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild even if merge commit list exists")
    parser.add_argument("-v", "--verbose", action="store_true", help="Display logs instead of progress bar")
    parser.add_argument(
        "-a",
        "--analysis",
        action="append",
        help="Name of an analysis to run",
    )
    args = parser.parse_args()
    global redis
    redis = setup_redis_connection()

    signal.signal(signal.SIGINT, signal_handler)

    analyses:list[Analysis]
    if not args.analysis:
        analyses = collect_analyses(['core'])
    else:
        analyses = collect_analyses(args.analysis)

    if not args.verbose:
        logger.disable("__main__");

    git_repo_name = args.git_repo_name
    force = args.force
    caches = os.environ.get("CACHES", "../../caches")
    git_dir = f"{caches}/repos/{git_repo_name}.git"
    
    if not os.path.isdir(git_dir):
        print(f"Error: {git_dir} does not exist")
        sys.exit(1)

    for analysis in analyses:
        if already_analysed(analysis, git_repo_name) and not force:
            print(f"Analysis data for repo {git_repo_name} of type {analysis.get_analysis_name()} already exists (use -f to force rebuild)")
            break

        conflict_candidates = collect_analysis_candidates(git_dir, git_repo_name)
        execute_analyses(analysis, conflict_candidates, args.verbose)

if __name__ == "__main__":
    main()
