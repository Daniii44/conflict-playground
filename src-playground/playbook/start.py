#!/usr/bin/env python3

import argparse
from collections import defaultdict
from dataclasses import replace
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
from common.redis_util import RESOLUTION_CONFLICT_PREFIX, RUNTIME_ACTIVE_PLAYGROUND_PREFIX, setup_redis_connection
from playbook.playgrounds import (
    Playground,
    format_playground_summary_line,
    load_playbook,
    load_playbook_result,
    print_playground_summary,
    resolve_playground_merge_sha,
)

# playbook-start <playbook>

# Lock to ensure hook dispatch is synchronous (only one at a time)
hook_lock = threading.Lock()
setup_lock = threading.Lock()

# Flag to signal shutdown
shutdown_requested = threading.Event()


def log(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"{timestamp} [playbook-start] {message}", flush=True)


def signal_handler(signum, frame):
    """Handle Ctrl+C to gracefully shutdown"""
    log("interrupt received, shutting down")
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


def hook_error_message(hook_result: dict | None) -> str | None:
    if hook_result is None:
        return None
    message = hook_result.get("message")
    if isinstance(message, str) and message.startswith("Error"):
        return message
    return None


def save_resolution(redis: Redis, playground_name: str, active_playground_key: str) -> str:
    active_playground_data = redis.json().get(active_playground_key)
    if not active_playground_data:
        raise RuntimeError(f"No active playground found with name {playground_name}")

    active_playground = ActivePlayground.model_validate(active_playground_data)
    resolved_at = datetime.now()
    proposed_resolution = collect_proposed_resolution(playground_name)
    hook_error = hook_error_message(active_playground.hook_result)
    if proposed_resolution.git_archive is None and hook_error is not None:
        if proposed_resolution.error:
            proposed_resolution.error = f"{hook_error}; {proposed_resolution.error}"
        else:
            proposed_resolution.error = hook_error

    resolution = ConflictResolution(
        configuration=active_playground.configuration,
        resolution_end=resolved_at,
        hook_result=active_playground.hook_result,
        proposed_resolution=proposed_resolution,
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

    result = capture_git(
        "-C", str(path), "submodule", "status", "--recursive", check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "no error output"
        log(
            "could not inspect all submodules "
            f"(exit {result.returncode}): {detail}"
        )

    uninitialized_submodules = [
        line for line in result.stdout.splitlines()
        if line.startswith("-")
    ]
    if uninitialized_submodules:
        sample = "; ".join(uninitialized_submodules[:3])
        extra = "" if len(uninitialized_submodules) <= 3 else f"; +{len(uninitialized_submodules) - 3} more"
        log(f"playground has uninitialized submodules: {sample}{extra}")


def playground_with_resolved_merge_sha(pg: Playground) -> Playground:
    merge_sha = resolve_playground_merge_sha(pg)
    if pg.merge_sha == merge_sha:
        return pg

    return replace(pg, merge_sha=merge_sha, parent_shas=None)


def resolution_key_match(repo_name: str, merge_sha: str) -> str:
    return f"{RESOLUTION_CONFLICT_PREFIX}{repo_name}-{merge_sha}:*"


def count_existing_resolutions(redis: Redis, repo_name: str, merge_sha: str) -> int:
    return sum(
        1
        for _ in redis.scan_iter(match=resolution_key_match(repo_name, merge_sha))
    )


def prune_playgrounds_by_repetition_limit(
    playgrounds: list[Playground],
    redis: Redis,
    repetition_limit: int,
) -> list[Playground]:
    existing_counts: dict[tuple[str, str], int] = {}
    selected_counts: dict[tuple[str, str], int] = defaultdict(int)
    selected_playgrounds = []
    pruned_playgrounds = []

    for pg in playgrounds:
        resolved_pg = playground_with_resolved_merge_sha(pg)
        key = (resolved_pg.repo_name, resolved_pg.merge_sha)
        if key not in existing_counts:
            existing_counts[key] = count_existing_resolutions(
                redis,
                resolved_pg.repo_name,
                resolved_pg.merge_sha,
            )

        if existing_counts[key] + selected_counts[key] >= repetition_limit:
            pruned_playgrounds.append(resolved_pg)
            continue

        selected_counts[key] += 1
        selected_playgrounds.append(resolved_pg)

    if pruned_playgrounds:
        print(f"\nPruned {len(pruned_playgrounds)} playgrounds at repetition limit {repetition_limit}:")
        for pg in pruned_playgrounds:
            existing_count = existing_counts[(pg.repo_name, pg.merge_sha)]
            print(
                f"  - {pg.repo_name}: {pg.merge_sha} "
                f"({existing_count} existing resolution keys)"
            )

    return selected_playgrounds


def process_playground(pg: Playground, redis: Redis, index: int, total: int) -> bool:
    """Process a single playground: setup, dispatch, assess, clean"""
    # Check if shutdown was requested before starting
    if shutdown_requested.is_set():
        log(f"[{index}/{total}] skipping {pg.repo_name} - shutdown requested")
        return False

    started_at = datetime.now()
    playground_name: str | None = None
    try:
        with setup_lock:
            # Check again after acquiring lock
            if shutdown_requested.is_set():
                log(f"[{index}/{total}] skipping {pg.repo_name} - shutdown requested after setup lock")
                return False

            merge_sha = resolve_playground_merge_sha(pg)
            log(f"[{index}/{total}] setting up playground for repo={pg.repo_name} merge={merge_sha}")
            result = subprocess.run(
                ["playground-setup", pg.repo_name, merge_sha],
                check=True,
                capture_output=True,
                text=True
            )
            playground_name = result.stdout.strip()
            if not playground_name:
                raise RuntimeError("playground-setup did not report a playground name")
            log(
                f"[{index}/{total}] playground-setup returned playground={playground_name} "
                f"stderr_chars={len(result.stderr)}"
            )
            validate_playground_setup(playground_name)
            log(f"[{index}/{total}] validated playground={playground_name}")

        # Hook dispatch must be synchronous (only one at a time)
        with hook_lock:
            # Check shutdown before hook dispatch
            if shutdown_requested.is_set():
                log(f"[{index}/{total}] stopping {pg.repo_name} - shutdown requested before hook dispatch")
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
            log(
                f"[{index}/{total}] stored active playground metadata at key={redis_active_playground_key} "
                f"hook_type={activePlayground.configuration.hook_type}"
            )

            log(f"[{index}/{total}] dispatching hook task for playground={playground_name}")
            subprocess.run(["hook-dispatch-task", playground_name], check=True)
            active_playground_data = redis.json().get(redis_active_playground_key) or {}
            hook_result = active_playground_data.get("hook_result")
            hook_message = hook_result.get("message") if isinstance(hook_result, dict) else None
            log(
                f"[{index}/{total}] hook dispatch returned for playground={playground_name} "
                f"hook_message={hook_message!r}"
            )

            log(f"[{index}/{total}] saving resolution for playground={playground_name}")
            resolution_key = save_resolution(redis, playground_name, redis_active_playground_key)
            log(f"[{index}/{total}] stored resolution at key={resolution_key}")

            log(f"[{index}/{total}] cleaning up playground={playground_name} repo={pg.repo_name}")
            subprocess.run(["playground-rm", playground_name], check=True)
            redis.delete(redis_active_playground_key)
            log(f"[{index}/{total}] removed playground={playground_name} and deleted key={redis_active_playground_key}")

        log(
            f"[{index}/{total}] completed repo={pg.repo_name} merge={merge_sha} "
            f"in {(datetime.now() - started_at).total_seconds():.2f}s"
        )
        return True
    except (RuntimeError, subprocess.CalledProcessError) as e:
        log(
            f"[{index}/{total}] error processing repo={pg.repo_name} playground={playground_name} "
            f"after {(datetime.now() - started_at).total_seconds():.2f}s: {type(e).__name__}: {e}"
        )
        return False


def main():
    parser = argparse.ArgumentParser(description="Start a playbook")
    parser.add_argument("playbook", help="Name of the playbook", nargs='?', default="default")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N playgrounds")
    parser.add_argument("--pool", type=int, default=3, help="Number of parallel playgrounds")
    parser.add_argument(
        "--repetition-limit",
        type=int,
        default=3,
        help="Skip merges that already have this many saved resolution keys",
    )
    args = parser.parse_args()
    if args.repetition_limit < 0:
        parser.error("--repetition-limit must be non-negative")

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

    playgrounds = prune_playgrounds_by_repetition_limit(
        playgrounds,
        redis,
        args.repetition_limit,
    )

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
