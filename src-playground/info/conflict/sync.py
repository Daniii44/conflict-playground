#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from common.redis_util import setup_redis_connection

# Script to collect all dirty merge commits in a bare git repository
# Usage: python collect-conflict.py <git-repo-name> [-f]

# FIXME
# fatal: unable to read tree (322895d3a525e8e6afc5b8ae049a73c41628b280)
# fatal: unable to read tree (26cfa9e41bbc6701fe9a751b7f91ffa48930c6d1
# fatal: unable to read tree (280ea2683eb11d4ecd722b12634b60d5bcd9a188)

# FIXME
# Stalls at 20892/20893 for git - maybe related with "unable to read tree"

def main():
    parser = argparse.ArgumentParser(description="Collect conflict merge commits from a bare git repository")
    parser.add_argument("git_repo_name", help="Name of the bare git repository")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild even if merge commit list exists")
    args = parser.parse_args()

    redis = setup_redis_connection()

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
    if result.stdout.strip() != "0":
        print(f"Merge commit list for repo {git_repo_name} already exists with {result.stdout.strip()} entries, skipping collection (use -f to force rebuild)")
        sys.exit(0)
    
    # Get all merge commit SHAs
    rev_list_cmd = ["git", f"--git-dir={git_dir}", "rev-list", "--merges", "HEAD"]
    try:
        rev_list = subprocess.check_output(rev_list_cmd, text=True).splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Error running git rev-list: {e}")
        sys.exit(1)

    total_merges_count = len(rev_list)
    processed_merges_count = 0
    processed_merges_count_lock = threading.Lock()
    start_time = time.time()
    last_status_len = 0
    dirty_merges_count = 0
    dirty_merges_count_lock = threading.Lock()

    def process_sha(sha):
        show_cmd = ["git", f"--git-dir={git_dir}", "show", "--remerge-diff", "--format=", sha]
        try:
            diff = subprocess.check_output(show_cmd, text=True)
        except subprocess.CalledProcessError:
            diff = ""
        dirty = False
        if diff.strip():
            dirty = True
            conflict_info = {
                "repo": git_repo_name,
                "sha": sha,
                "parent_clount": 2,
                "conflict_count": diff.count("<<<<<<<"),
                "conflict_difficulty": "unknown", # conflict_difficulty: pattern, interleaved, new-tokens, uncaught-conflict
            }
            redis.hset("info:conflict:" + sha, mapping=conflict_info)

            with dirty_merges_count_lock:
                nonlocal dirty_merges_count
                dirty_merges_count += 1
        with processed_merges_count_lock:
            nonlocal processed_merges_count
            processed_merges_count += 1
        return dirty

    max_workers = os.cpu_count()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_sha, sha) for sha in rev_list]

        # Print status line with progress, speed, and ETA
        while True:
            with processed_merges_count_lock:
                done = processed_merges_count
            elapsed = time.time() - start_time
            speed = done / elapsed if elapsed > 0 else 0
            remaining = total_merges_count - done
            eta = remaining / speed if speed > 0 else 0
            status = f"Processed: {done}/{total_merges_count} | Speed: {speed:.2f}/s | ETA: {eta:.1f}s"
            print("\r" + status + " " * max(0, last_status_len - len(status)), end="", flush=True)
            last_status_len = len(status)
            if done >= total_merges_count:
                break
            time.sleep(0.5)
        print()  # Newline after status
    print(f"Dirty merges found: {dirty_merges_count}")

if __name__ == "__main__":
    main()
