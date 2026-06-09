#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from functools import cache
import os
from pathlib import Path
import sys

import yaml

from common.git_util import capture_git
from common.repo_cache import repo_cache_key
from info.conflict.list import ConflictRecord, list_conflict_records


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


def print_playground_summary(playgrounds: list[Playground]) -> None:
    print(f"Loaded {len(playgrounds)} playgrounds:")
    for pg in playgrounds:
        print(format_playground_summary_line(pg))


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


def load_playbook(playbook_path: str | Path) -> list[Playground]:
    """Load playbook and create Playground objects."""
    with open(playbook_path, "r") as f:
        data = yaml.safe_load(f)

    playbook = data["playbook"]
    config = playbook.get("config", {})
    conflict_types = config.get("conflict-types") or []
    conflict_type_targets = parse_conflict_type_targets(config)
    conflict_query_types = conflict_types
    if conflict_type_targets is not None and not conflict_query_types:
        conflict_query_types = conflict_type_targets.target_types()

    playgrounds = []
    if not playbook["sources"]:
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
        for source in playbook["sources"]:
            repo_url = source["repo_url"]
            repo_name = repo_cache_key(repo_url)

            override_shas = source.get("override_merge_shas", [])
            if override_shas:
                for override in override_shas:
                    playgrounds.append(playground_from_override(repo_name, override))
            else:
                limit = source.get("limit", 1)
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


def resolve_playbook_path(playbook: str) -> Path:
    playbooks = os.environ.get("PLAYBOOKS")
    if not playbooks:
        print("PLAYBOOKS environment variable is not set", file=sys.stderr)
        sys.exit(1)

    playbook_path = Path(playbooks) / f"{playbook}.yaml"
    if not playbook_path.is_file():
        print(f"No such playbook: {playbook_path}", file=sys.stderr)
        sys.exit(1)

    return playbook_path


def main() -> None:
    parser = argparse.ArgumentParser(description="List playgrounds generated by a playbook")
    parser.add_argument("playbook", nargs="?", default="default", help="Name of the playbook")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N playgrounds")
    args = parser.parse_args()

    playgrounds = load_playbook(resolve_playbook_path(args.playbook))
    if args.skip > 0:
        playgrounds = playgrounds[args.skip:]

    print_playground_summary(playgrounds)


if __name__ == "__main__":
    main()
