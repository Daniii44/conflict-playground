#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys

import yaml

from common.repo_cache import repo_cache_key
from dataset.schesch.merge_lookup import resolve_unique_merge_sha_from_parents
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
            return f"{self.parent_shas[0]}..{self.parent_shas[1]}"

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


def format_conflict_type_target_summary_lines(
    playgrounds: list[Playground],
    target_ratios: dict[str, float] | None,
) -> list[str]:
    if not target_ratios:
        return []

    total = len(playgrounds)
    selected_counts = {conflict_type: 0 for conflict_type in target_ratios}
    other_count = 0
    for pg in playgrounds:
        if pg.conflict_type in selected_counts:
            selected_counts[pg.conflict_type] += 1
        else:
            other_count += 1

    lines = ["ConflictTypeTargets achieved:"]
    for conflict_type, target_ratio in target_ratios.items():
        count = selected_counts[conflict_type]
        actual_ratio = count / total if total else 0
        lines.append(
            f"  - {conflict_type}: {count}/{total} "
            f"({actual_ratio:.1%}; target {target_ratio:.1%})"
        )

    if other_count:
        actual_ratio = other_count / total if total else 0
        lines.append(f"  - other: {other_count}/{total} ({actual_ratio:.1%}; no target)")

    return lines


def print_playground_summary(
    playgrounds: list[Playground],
    target_ratios: dict[str, float] | None = None,
) -> None:
    print(f"Loaded {len(playgrounds)} playgrounds:")
    for pg in playgrounds:
        print(format_playground_summary_line(pg))
    for line in format_conflict_type_target_summary_lines(playgrounds, target_ratios):
        print(line)


@dataclass
class PlaybookLoadResult:
    playgrounds: list[Playground]
    conflict_type_target_ratios: dict[str, float] | None = None


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

    if isinstance(override, dict) and "parents" in override:
        parent_shas = override["parents"]
        if (
            not isinstance(parent_shas, list)
            or len(parent_shas) != 2
            or not all(isinstance(parent_sha, str) for parent_sha in parent_shas)
        ):
            raise ValueError(f"Unsupported override_merge_shas entry for {repo_name}: {override!r}")
        return Playground(repo_name=repo_name, parent_shas=(parent_shas[0], parent_shas[1]))

    raise ValueError(f"Unsupported override_merge_shas entry for {repo_name}: {override!r}")


def resolve_playground_merge_sha(pg: Playground) -> str:
    if pg.merge_sha:
        return pg.merge_sha
    if pg.parent_shas:
        return resolve_unique_merge_sha_from_parents(pg.repo_name, pg.parent_shas)

    raise RuntimeError(f"Playground for {pg.repo_name} has no merge_sha")


def load_playbook_result(playbook_path: str | Path) -> PlaybookLoadResult:
    """Load playbook and create Playground objects with report metadata."""
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

    target_ratios = None
    if conflict_type_targets is not None:
        target_ratios = dict(conflict_type_targets.target_ratios)

    return PlaybookLoadResult(
        playgrounds=playgrounds,
        conflict_type_target_ratios=target_ratios,
    )


def load_playbook(playbook_path: str | Path) -> list[Playground]:
    """Load playbook and create Playground objects."""
    return load_playbook_result(playbook_path).playgrounds


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

    result = load_playbook_result(resolve_playbook_path(args.playbook))
    playgrounds = result.playgrounds
    if args.skip > 0:
        playgrounds = playgrounds[args.skip:]

    print_playground_summary(playgrounds, result.conflict_type_target_ratios)


if __name__ == "__main__":
    main()
