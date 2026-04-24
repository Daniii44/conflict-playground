#!/usr/bin/env python3

import os
import sys
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

# Script to collect all dirty merge commits in a bare git repository
# Usage: python collect_dirty_merges.py <git-repo-name>

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bare-git-repo>")
        sys.exit(1)

    git_repo_name = sys.argv[1]
    caches = os.environ.get("CACHES", "../../caches")
    git_dir = f"{caches}/repos/{git_repo_name}.git"
    merge_commit_dir = os.path.join(caches, "merges/dirty")
    merge_commit_list = os.path.join(merge_commit_dir, f"{git_repo_name}.txt")

    if not os.path.isdir(git_dir):
        print(f"Error: {git_dir} does not exist")
        sys.exit(1)

    # Setup files
    os.makedirs(merge_commit_dir, exist_ok=True)
    if os.path.exists(merge_commit_list):
        backup_path = merge_commit_list + ".backup"
        os.rename(merge_commit_list, backup_path)
    Path(merge_commit_list).touch()

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
    file_lock = threading.Lock()
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
            with file_lock:
                with open(merge_commit_list, "a") as f:
                    f.write(sha + "\n")
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
