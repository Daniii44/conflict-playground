#!/usr/bin/env python3

from asyncio import futures
import signal

from loguru import logger
import os
import sys
import subprocess
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import threading
import time
from common.redis_util import setup_redis_connection
from common.merge_tree import MergeResult, parse_merge_result, prune_auto_merged

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

def collect_parents(git_dir: str, sha: str) -> list[str]:
    show_cmd = ["git", f"--git-dir={git_dir}", "show", "--no-patch", "--format=%P", sha]
    try:
        parents = subprocess.check_output(show_cmd, text=True).strip().split()
    except subprocess.CalledProcessError as e:
        if e.returncode == -signal.SIGINT:
            global exiting
            exiting = True
            sys.exit(0)
        logger.error(f"Error running git show for {sha}: {e}")
        return []
    return parents

def process_sha(git_dir: str, sha: str) -> MergeResult | None:
    global exiting
    if exiting:
        sys.exit(0)

    parents = collect_parents(git_dir, sha)
    if len(parents) < 2:
        logger.error(f"Merge commit {sha} has less than 2 parents, skipping")
        return None
    elif len(parents) > 2:
        # Not supporting octopus merges for now, since git doesn't even allow to perform non trivial octopus merges directly.
        # TODO: Take a look whether there are complex octoopus merges nonetheless
        logger.info(f"Merge commit {sha} has more than 2 parents, skipping")
        return None
    
    merge_tree_cmd = ["git", f"--git-dir={git_dir}", "merge-tree", "-z", parents[0], parents[1]]
    
    try:
        subprocess.check_output(merge_tree_cmd, text=True)
        logger.debug(f"No conflict for merge {sha}")
    except subprocess.CalledProcessError as e:
        if e.returncode == -signal.SIGINT:
            exiting = True
            sys.exit(0)

        mergeResult = prune_auto_merged(parse_merge_result(e.output.encode()))

        for logical_conflict in mergeResult.logical_conflicts:
            logger.info(f"{logical_conflict.type}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Collect conflict merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild even if merge commit list exists")
    parser.add_argument("-v", "--verbose", action="store_true", help="Display logs instead of progress bar")
    args = parser.parse_args()

    redis = setup_redis_connection()

    signal.signal(signal.SIGINT, signal_handler)

    git_repo_name = args.git_repo_name
    force = args.force
    caches = os.environ.get("CACHES", "../../caches")
    git_dir = f"{caches}/repos/{git_repo_name}.git"
    
    if not os.path.isdir(git_dir):
        print(f"Error: {git_dir} does not exist")
        sys.exit(1)

    result = subprocess.run(
        ["info-conflict-count", git_repo_name],
        capture_output=True,
        text=True,
        check=True
    )
    if result.stdout.strip() != "0" and not force:
        print(f"Merge commit list for repo {git_repo_name} already exists with {result.stdout.strip()} entries, skipping collection (use -f to force rebuild)")
        sys.exit(0)
    
    conflict_candidates = collect_conflict_candidate_sha(git_dir)
    max_workers = os.cpu_count()

    if not args.verbose:
        logger.disable("__main__");

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_sha, git_dir, sha) for sha in conflict_candidates]

        # Wrap as_completed in tqdm to get a live progress bar
        if not args.verbose:
            with tqdm(total=len(futures), desc="Processing SHAs") as pbar:
                for future in as_completed(futures):
                    result = future.result() # Get the result of the job
                    pbar.update(1)           # Increment the progress bar

if __name__ == "__main__":
    main()
