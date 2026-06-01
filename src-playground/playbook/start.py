#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
import os
import signal
import subprocess
import sys
from redis import Redis
import yaml
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from common.active_playground_models import Configuration, ActivePlayground
from common.repo_cache import repo_cache_key
from common.redis_util import RUNTIME_ACTIVE_PLAYGROUND_PREFIX, setup_redis_connection
from info.conflict.list import list_conflicts

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


@dataclass
class Playground:
    repo_name: str
    merge_sha: str


def load_playbook(playbook_path: str) -> list[Playground]:
    """Load playbook and create Playground objects"""
    with open(playbook_path, 'r') as f:
        data = yaml.safe_load(f)

    playbook = data['playbook']
    conflict_types = playbook.get("config", {}).get("conflict-types") or []
    playgrounds = []
    if not playbook['sources']:
        conflicts = list_conflicts(conflict_types=conflict_types)
        for (repo, merge_commit_oid) in conflicts:
            playgrounds.append(Playground(repo_name=repo, merge_sha=merge_commit_oid))
    else:
        for source in playbook['sources']:
            repo_url = source['repo_url']
            repo_name = repo_cache_key(repo_url)

            # Support override_merge_shas (explicit list) or limit (number of SHAs from conflicts)
            override_shas = source.get('override_merge_shas', [])
            if override_shas:
                # Use explicitly provided merge SHAs
                for merge_sha in override_shas:
                    playgrounds.append(Playground(repo_name=repo_name, merge_sha=merge_sha))
            else:
                # Use limit to get SHAs from conflict
                limit = source.get('limit', 1)
                
                for conflict in list_conflicts(repos=[repo_name], conflict_types=conflict_types, limit=limit):
                    playgrounds.append(Playground(repo_name=repo_name, merge_sha=conflict[1]))

    return playgrounds


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
                
            print(f"[{index}/{total}] Setting up playground for {pg.repo_name} ({pg.merge_sha})")
            result = subprocess.run(
                ["playground-setup", pg.repo_name, pg.merge_sha], 
                check=True, 
                capture_output=True, 
                text=True
            )
            playground_name = result.stdout.strip()
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

            print(f"[{index}/{total}] Evaluating Result")
            subprocess.run(["evaluation-assess", playground_name], check=True)
            
            print(f"[{index}/{total}] Cleaning up playground for {pg.repo_name}...")
            subprocess.run(["playground-rm", pg.repo_name], check=True)
            redis.delete(redis_active_playground_key)
            
        return True
    except subprocess.CalledProcessError as e:
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
    playgrounds = load_playbook(playbook_path)

    # Apply skip
    if args.skip > 0:
        playgrounds = playgrounds[args.skip:]

    print(f"Loaded {len(playgrounds)} playgrounds:")
    for pg in playgrounds:
        print(f"  - {pg.repo_name}: {pg.merge_sha}")

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
