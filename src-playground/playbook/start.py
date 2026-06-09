#!/usr/bin/env python3

import argparse
from datetime import datetime
from functools import cache
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
from common.git_util import capture_git
from common.repo_cache import repo_cache_key
from common.resolution_models import ConflictResolution, ProposedResolution, resolution_record_key
from common.redis_util import RUNTIME_ACTIVE_PLAYGROUND_PREFIX, setup_redis_connection
from info.conflict.list import ConflictRecord, list_conflict_records

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
    merge_sha: str | None = None
    parent_shas: tuple[str, str] | None = None
    conflict_type: str | None = None
    conflict_types: tuple[str, ...] = tuple()

    def target_label(self) -> str:
        if self.merge_sha:
            return self.merge_sha

        if self.parent_shas:
            return f"{self.parent_shas[0]}_{self.parent_shas[1]}"

        return "<missing merge target>"

    def conflict_type_label(self) -> str:
        if self.conflict_types:
            return ", ".join(self.conflict_types)

        return self.conflict_type or "unknown"


def playground_from_conflict_record(
    record: ConflictRecord,
    repo_name: str | None = None,
    conflict_type: str | None = None,
) -> Playground:
    return Playground(
        repo_name=repo_name or record.repo,
        merge_sha=record.merge_commit_oid,
        conflict_type=conflict_type,
        conflict_types=record.conflict_types,
    )


def format_playground_summary_line(pg: Playground) -> str:
    return f"  - {pg.repo_name}: {pg.target_label()} [{pg.conflict_type_label()}]"


@dataclass
class ConflictTypeTargets:
    target_ratios: dict[str, float]
    selected_counts: dict[str, int]
    selected_total: int = 0

    def target_types(self) -> list[str]:
        return list(self.target_ratios)

    def choose_type(self, record: ConflictRecord) -> str | None:
        matching_types = [
            conflict_type
            for conflict_type in record.conflict_types
            if conflict_type in self.target_ratios
        ]
        if not matching_types:
            return record.conflict_types[0] if record.conflict_types else None

        next_total = self.selected_total + 1
        return max(
            matching_types,
            key=lambda conflict_type: (
                self.target_ratios[conflict_type] * next_total
                - self.selected_counts.get(conflict_type, 0),
                -self.target_types().index(conflict_type),
            ),
        )

    def score(self, record: ConflictRecord) -> float:
        selected_type = self.choose_type(record)
        if selected_type is None or selected_type not in self.target_ratios:
            return float("-inf")

        next_total = self.selected_total + 1
        return self.target_ratios[selected_type] * next_total - self.selected_counts.get(selected_type, 0)

    def mark_selected(self, conflict_type: str | None) -> None:
        self.selected_total += 1
        if conflict_type in self.target_ratios:
            self.selected_counts[conflict_type] = self.selected_counts.get(conflict_type, 0) + 1


def parse_conflict_type_targets(config: dict) -> ConflictTypeTargets | None:
    raw_targets = (
        config.get("conflict-type-percentages")
        or config.get("conflict-type-targets")
        or {}
    )
    if not raw_targets:
        return None

    if not isinstance(raw_targets, dict):
        raise ValueError("playbook.config.conflict-type-percentages must be a mapping")

    target_values = {}
    for conflict_type, percentage in raw_targets.items():
        if not isinstance(conflict_type, str) or not conflict_type:
            raise ValueError("conflict type target keys must be non-empty strings")
        if not isinstance(percentage, (int, float)) or percentage <= 0:
            raise ValueError(f"Target percentage for {conflict_type} must be a positive number")
        target_values[conflict_type] = float(percentage)

    total = sum(target_values.values())
    return ConflictTypeTargets(
        target_ratios={
            conflict_type: percentage / total
            for conflict_type, percentage in target_values.items()
        },
        selected_counts={conflict_type: 0 for conflict_type in target_values},
    )


def select_conflict_records(
    candidates: list[ConflictRecord],
    limit: int,
    targets: ConflictTypeTargets,
) -> list[tuple[ConflictRecord, str | None]]:
    remaining = list(candidates)
    selected = []

    while remaining and len(selected) < limit:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (targets.score(remaining[index]), -index),
        )
        record = remaining.pop(best_index)
        selected_type = targets.choose_type(record)
        targets.mark_selected(selected_type)
        selected.append((record, selected_type))

    return selected


def playground_from_override(repo_name: str, override) -> Playground:
    if isinstance(override, str):
        return Playground(repo_name=repo_name, merge_sha=override)

    if not isinstance(override, dict):
        raise ValueError(f"Unsupported override_merge_shas entry for {repo_name}: {override!r}")

    merge_sha = override.get("merge_sha")
    if isinstance(merge_sha, str) and merge_sha:
        return Playground(repo_name=repo_name, merge_sha=merge_sha)

    parents = override.get("parents")
    if (
        isinstance(parents, list)
        and len(parents) == 2
        and all(isinstance(parent, str) and parent for parent in parents)
    ):
        return Playground(repo_name=repo_name, parent_shas=(parents[0], parents[1]))

    raise ValueError(f"Unsupported override_merge_shas entry for {repo_name}: {override!r}")


@cache
def merge_parent_index(repo_name: str) -> dict[frozenset[str], list[str]]:
    caches = Path(os.environ.get("CACHES", str(Path.home() / "caches")))
    bare_repo = caches / "repos" / repo_name
    if not bare_repo.is_dir():
        raise RuntimeError(f"Bare repository {bare_repo} does not exist")

    result = capture_git(
        f"--git-dir={bare_repo}",
        "rev-list",
        "--all",
        "--merges",
        "--parents",
    )

    index: dict[frozenset[str], list[str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        merge_sha = parts[0]
        parents = parts[1:]
        if len(parents) != 2:
            continue

        index.setdefault(frozenset(parents), []).append(merge_sha)

    return index


def resolve_merge_sha_from_parents(repo_name: str, parent_shas: tuple[str, str]) -> str:
    matches = merge_parent_index(repo_name).get(frozenset(parent_shas), [])

    if not matches:
        raise RuntimeError(
            f"No merge commit found in {repo_name} with parents {parent_shas[0]} and {parent_shas[1]}"
        )

    if len(matches) > 1:
        print(
            f"Found {len(matches)} merge commits in {repo_name} with parents "
            f"{parent_shas[0]} and {parent_shas[1]}; using {matches[0]}"
        )

    return matches[0]


def resolve_playground_merge_sha(pg: Playground) -> str:
    if pg.merge_sha:
        return pg.merge_sha

    if pg.parent_shas:
        return resolve_merge_sha_from_parents(pg.repo_name, pg.parent_shas)

    raise RuntimeError(f"Playground for {pg.repo_name} has neither merge_sha nor parent_shas")


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


def load_playbook(playbook_path: str) -> list[Playground]:
    """Load playbook and create Playground objects"""
    with open(playbook_path, 'r') as f:
        data = yaml.safe_load(f)

    playbook = data['playbook']
    config = playbook.get("config", {})
    conflict_types = config.get("conflict-types") or []
    conflict_type_targets = parse_conflict_type_targets(config)
    conflict_query_types = conflict_types
    if conflict_type_targets is not None and not conflict_query_types:
        conflict_query_types = conflict_type_targets.target_types()

    playgrounds = []
    if not playbook['sources']:
        conflicts = list_conflict_records(conflict_types=conflict_query_types)
        if conflict_type_targets is None:
            for conflict in conflicts:
                playgrounds.append(playground_from_conflict_record(conflict))
        else:
            for conflict, selected_type in select_conflict_records(
                conflicts,
                len(conflicts),
                conflict_type_targets,
            ):
                playgrounds.append(playground_from_conflict_record(conflict, conflict_type=selected_type))
    else:
        for source in playbook['sources']:
            repo_url = source['repo_url']
            repo_name = repo_cache_key(repo_url)

            # Support override_merge_shas (explicit list) or limit (number of SHAs from conflicts)
            override_shas = source.get('override_merge_shas', [])
            if override_shas:
                # Use explicitly provided merge SHAs or parent-pair overrides.
                for override in override_shas:
                    playgrounds.append(playground_from_override(repo_name, override))
            else:
                # Use limit to get SHAs from conflict
                limit = source.get('limit', 1)
                if conflict_type_targets is None:
                    for conflict in list_conflict_records(
                        repos=[repo_name],
                        conflict_types=conflict_types,
                        limit=limit,
                    ):
                        playgrounds.append(playground_from_conflict_record(conflict, repo_name=repo_name))
                else:
                    conflicts = list_conflict_records(
                        repos=[repo_name],
                        conflict_types=conflict_query_types,
                    )
                    for conflict, selected_type in select_conflict_records(
                        conflicts,
                        limit,
                        conflict_type_targets,
                    ):
                        playgrounds.append(
                            playground_from_conflict_record(
                                conflict,
                                repo_name=repo_name,
                                conflict_type=selected_type,
                            )
                        )

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
    playgrounds = load_playbook(playbook_path)

    # Apply skip
    if args.skip > 0:
        playgrounds = playgrounds[args.skip:]

    print(f"Loaded {len(playgrounds)} playgrounds:")
    for pg in playgrounds:
        print(format_playground_summary_line(pg))

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
