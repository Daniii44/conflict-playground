#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
import os
import signal
import subprocess
import sys
from redis import Redis
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from common.active_playground_models import Configuration, ActivePlayground
from common.git_util import capture_git
from common.resolution_models import ConflictResolution, ProposedResolution, resolution_record_key
from common.redis_util import RUNTIME_ACTIVE_PLAYGROUND_PREFIX, setup_redis_connection
from playbook.playgrounds import (
    Playground,
    format_playground_summary_line,
    load_playbook,
    load_playbook_result,
    merge_parent_index,
    print_playground_summary,
    resolve_merge_sha_from_parents,
    resolve_playground_merge_sha,
)

# playbook-start <playbook>

# Lock to ensure hook dispatch is synchronous (only one at a time)
hook_lock = threading.Lock()
setup_lock = threading.Lock()

# Flag to signal shutdown
shutdown_requested = threading.Event()


def signal_handler(signum, frame):
    """Handle Ctrl+C to gracefully shutdown"""
    print("\nInterrupt received, shutting down...")
    shutdown_requested.set()


def merge_parent_shas(playground_path: str, ref: str) -> list[str]:
    result = capture_git("-C", playground_path, "show", "-s", "--format=%P", ref)
    return result.stdout.split()


def collect_proposed_resolution(playground_name: str) -> ProposedResolution:
    playgrounds = os.environ.get("PLAYGROUNDS")
    if playgrounds is None:
        return ProposedResolution(error="PLAYGROUNDS environment variable is not set")

    playground_path = f"{playgrounds}/{playground_name}"
    try:
        actual_resolution_sha = playground_name.rsplit("-", 1)[1]
    except IndexError:
        return ProposedResolution(error=f"Could not extract merge SHA from playground name: {playground_name}")

    head_result = capture_git("-C", playground_path, "rev-parse", "HEAD", check=False)
    if head_result.returncode != 0:
        error = head_result.stderr.strip() or head_result.stdout.strip()
        return ProposedResolution(
            actual_resolution_sha=actual_resolution_sha,
            error=f"Could not read resolved HEAD: {error}",
        )

    commit_sha = head_result.stdout.strip()
    try:
        expected_parents = merge_parent_shas(playground_path, actual_resolution_sha)
        resolved_parents = merge_parent_shas(playground_path, commit_sha)
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip()
        return ProposedResolution(
            commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            error=f"Could not verify resolved merge parents: {message}",
        )

    if set(resolved_parents) != set(expected_parents):
        expected = " and ".join(expected_parents) if expected_parents else "<none>"
        resolved = " and ".join(resolved_parents) if resolved_parents else "<none>"
        return ProposedResolution(
            commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            error=f"Resolved HEAD did not merge the expected branches: expected parents {expected}; got {resolved}",
        )

    archive_result = subprocess.run(
        ["playground-save", playground_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if archive_result.returncode != 0:
        error = archive_result.stderr.strip() or archive_result.stdout.strip()
        return ProposedResolution(
            commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            error=f"Could not archive proposed resolution: {error}",
        )

    return ProposedResolution(
        commit_sha=commit_sha,
        actual_resolution_sha=actual_resolution_sha,
        git_archive=archive_result.stdout.strip(),
    )


def save_resolution(redis: Redis, playground_name: str, active_playground_key: str) -> str:
    active_playground_data = redis.json().get(active_playground_key)
    if not active_playground_data:
        raise RuntimeError(f"No active playground found with name {playground_name}")

    active_playground = ActivePlayground.model_validate(active_playground_data)
    resolved_at = datetime.now()
    resolution = ConflictResolution(
        configuration=active_playground.configuration,
        resolution_end=resolved_at,
        hook_result=active_playground.hook_result,
        proposed_resolution=collect_proposed_resolution(playground_name),
    )
    resolution_key = resolution_record_key(playground_name, resolved_at)
    redis.json().set(resolution_key, "$", json.loads(resolution.model_dump_json()))
    return resolution_key


def playground_path(playground_name: str) -> Path:
    playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
    return playgrounds / playground_name


def validate_playground_setup(playground_name: str) -> None:
    path = playground_path(playground_name)
    if not path.is_dir():
        raise RuntimeError(f"playground path does not exist: {path}")

    capture_git("-C", str(path), "rev-parse", "--is-inside-work-tree")

    result = capture_git("-C", str(path), "submodule", "status", "--recursive")
    uninitialized_submodules = [
        line for line in result.stdout.splitlines()
        if line.startswith("-")
    ]
    if uninitialized_submodules:
        sample = "; ".join(uninitialized_submodules[:3])
        extra = "" if len(uninitialized_submodules) <= 3 else f"; +{len(uninitialized_submodules) - 3} more"
        raise RuntimeError(f"playground has uninitialized submodules: {sample}{extra}")


def process_playground(pg: Playground, redis: Redis, index: int, total: int) -> bool:
    """Process a single playground: setup, dispatch, assess, clean"""
    # Check if shutdown was requested before starting
    if shutdown_requested.is_set():
        print(f"[{index}/{total}] Skipping {pg.repo_name} - shutdown requested")
        return False
    
    try:
        with setup_lock:
            # Check again after acquiring lock
            if shutdown_requested.is_set():
                print(f"[{index}/{total}] Skipping {pg.repo_name} - shutdown requested")
                return False
                
            merge_sha = resolve_playground_merge_sha(pg)
            print(f"[{index}/{total}] Setting up playground for {pg.repo_name} ({merge_sha})")
            result = subprocess.run(
                ["playground-setup", pg.repo_name, merge_sha],
                check=True, 
                capture_output=True, 
                text=True
            )
            playground_name = result.stdout.strip()
            if not playground_name:
                raise RuntimeError("playground-setup did not report a playground name")
            validate_playground_setup(playground_name)
            print(f"[{index}/{total}] Created Playground: {playground_name}")

        # Hook dispatch must be synchronous (only one at a time)
        with hook_lock:
            # Check shutdown before hook dispatch
            if shutdown_requested.is_set():
                print(f"[{index}/{total}] Stopping {pg.repo_name} - shutdown requested")
                return False
                
            activePlayground = ActivePlayground(
                playground_name=playground_name,
                configuration=Configuration(
                    hook_type=os.environ.get("HOOK_TYPE", "unknown"),  # Placeholder, can be extended to read from playbook
                    playground_version=os.environ.get("PLAYGROUND_VERSION", "unknown"),
                    volume_type=os.environ.get("VOLUME_TYPE", "unknown"),
                    resolution_start=datetime.now()
                )
            )

            redis_active_playground_key = f"{RUNTIME_ACTIVE_PLAYGROUND_PREFIX}{playground_name}"
            redis.json().set(redis_active_playground_key, "$", json.loads(activePlayground.model_dump_json()))

            print(f"[{index}/{total}] Dispatching task to hook")
            subprocess.run(["hook-dispatch-task", playground_name], check=True)

            print(f"[{index}/{total}] Saving resolution")
            resolution_key = save_resolution(redis, playground_name, redis_active_playground_key)
            print(f"[{index}/{total}] Stored resolution at {resolution_key}")
            
            print(f"[{index}/{total}] Cleaning up playground for {pg.repo_name}...")
            subprocess.run(["playground-rm", playground_name], check=True)
            redis.delete(redis_active_playground_key)
            
        return True
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"[{index}/{total}] Error processing {pg.repo_name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Start a playbook")
    parser.add_argument("playbook", help="Name of the playbook", nargs='?', default="default")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N playgrounds")
    parser.add_argument("--pool", type=int, default=3, help="Number of parallel playgrounds")
    args = parser.parse_args()

    redis = setup_redis_connection()

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    playbooks = os.environ.get("PLAYBOOKS")
    playbook_path = f"{playbooks}/{args.playbook}.yaml"
    if not Path(playbook_path).is_file():
        print(f"No such playbook: {playbook_path}")
        sys.exit(1)
    load_result = load_playbook_result(playbook_path)
    playgrounds = load_result.playgrounds

    # Apply skip
    if args.skip > 0:
        playgrounds = playgrounds[args.skip:]

    print_playground_summary(playgrounds, load_result.conflict_type_target_ratios)

    print(f"\nStarting playbook execution with pool size {args.pool}...")
    
    total = len(playgrounds)
    completed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.pool) as executor:
        # Submit all tasks
        future_to_pg = {
            executor.submit(process_playground, pg, redis, i + args.skip + 1, total): pg 
            for i, pg in enumerate(playgrounds)
        }
        
        # Process results as they complete
        for future in as_completed(future_to_pg):
            # Check if shutdown was requested
            if shutdown_requested.is_set():
                print("\nShutdown requested, cancelling remaining tasks...")
                # Cancel pending futures
                for f in future_to_pg:
                    f.cancel()
                break
                
            pg = future_to_pg[future]
            try:
                success = future.result()
                if success:
                    completed += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"Exception processing {pg.repo_name}: {e}")
                failed += 1

    print(f"\nPlaybook execution complete! ({completed} succeeded, {failed} failed)")


if __name__ == "__main__":
    main()
