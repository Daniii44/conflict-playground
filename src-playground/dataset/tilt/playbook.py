#!/usr/bin/env python3

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.merge_tree import ConflictType
from common.redis_util import setup_redis_connection
from info.conflict.analysis.tilt_analysis import InfoConflictTilt


DATASET_NAME = "tilt"
DATASET_TILT_KEY = "dataset:tilt"
DATASET_TILT_PREFIX = "dataset:tilt:"
INFO_TILT_PREFIX = "info:conflict:tilt:"


@dataclass(frozen=True)
class TiltTarget:
    subdataset: str
    conflict_type: ConflictType
    count: int


@dataclass(frozen=True, order=True)
class TiltConflictIdentity:
    repo: str
    merge_sha: str

    def identifier(self) -> str:
        return f"{self.repo}:{self.merge_sha}"


@dataclass(frozen=True)
class TiltCandidate:
    identity: TiltConflictIdentity
    subdataset: str
    reason_conflict_type: ConflictType
    subdataset_purity: float
    reason_purity: float
    logical_conflict_count: int


@dataclass(frozen=True)
class TiltPlaybookBuildResult:
    selected: list[TiltCandidate]
    candidate_count: int
    candidate_counts_by_reason: dict[ConflictType, int]
    shortfalls_by_reason: dict[ConflictType, int]


TOP100_TARGETS: tuple[TiltTarget, ...] = (
    TiltTarget("content", ConflictType.CONFLICT_CONTENTS, 200),
    TiltTarget("content", ConflictType.CONFLICT_BINARY, 50),
    TiltTarget("modify/delete", ConflictType.CONFLICT_MODIFY_DELETE, 250),
    TiltTarget("rename", ConflictType.CONFLICT_RENAME_DELETE, 150),
    TiltTarget("rename", ConflictType.CONFLICT_RENAME_RENAME, 100),
    TiltTarget("directory", ConflictType.CONFLICT_DIR_RENAME_SUGGESTED, 200),
    TiltTarget("directory", ConflictType.CONFLICT_DIR_RENAME_SPLIT, 50),
)

TARGETS_BY_NAME: dict[str, tuple[TiltTarget, ...]] = {
    "top100": TOP100_TARGETS,
}


def default_playbook_output_path(target_name: str) -> Path:
    playbooks_env = os.environ.get("PLAYBOOKS")
    if playbooks_env:
        return Path(playbooks_env) / f"{target_name}.yaml"

    local_playbooks = Path.cwd() / "data" / "playbooks"
    if local_playbooks.exists():
        return local_playbooks / f"{target_name}.yaml"

    return Path("/root/playbooks") / f"{target_name}.yaml"


def targets_for_name(target_name: str) -> tuple[TiltTarget, ...]:
    try:
        return TARGETS_BY_NAME[target_name]
    except KeyError:
        known_targets = ", ".join(sorted(TARGETS_BY_NAME))
        raise ValueError(f"Unknown tilt target {target_name!r}; known targets: {known_targets}") from None


def target_by_conflict_type(targets: tuple[TiltTarget, ...]) -> dict[ConflictType, TiltTarget]:
    return {target.conflict_type: target for target in targets}


def tilt_info_key(identity: TiltConflictIdentity) -> str:
    return f"{INFO_TILT_PREFIX}{identity.repo}:{identity.merge_sha}"


def dataset_tilt_conflict_key(identity: TiltConflictIdentity) -> str:
    return f"{DATASET_TILT_PREFIX}{identity.identifier()}"


def parse_tilt_info_key(key: str) -> TiltConflictIdentity | None:
    if not key.startswith(INFO_TILT_PREFIX):
        return None

    rest = key.removeprefix(INFO_TILT_PREFIX)
    repo, separator, merge_sha = rest.rpartition(":")
    if not separator or not repo or not merge_sha:
        return None

    return TiltConflictIdentity(repo=repo, merge_sha=merge_sha)


def load_json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def collect_tilt_candidates(
    redis,
    *,
    targets: tuple[TiltTarget, ...],
) -> list[TiltCandidate]:
    targets_by_type = target_by_conflict_type(targets)
    candidates: list[TiltCandidate] = []

    for key in sorted(redis.scan_iter(match=f"{INFO_TILT_PREFIX}*")):
        identity = parse_tilt_info_key(key)
        if identity is None:
            logger.warning("Skipping malformed tilt info key: {}", key)
            continue

        data = redis.json().get(key)
        if data is None:
            continue

        tilt_info = InfoConflictTilt.model_validate(load_json_value(data))
        for subdataset in tilt_info.subdatasets:
            for conflict_type_purity in subdataset.conflict_types:
                target = targets_by_type.get(conflict_type_purity.type)
                if target is None or target.subdataset != subdataset.name:
                    continue

                candidates.append(
                    TiltCandidate(
                        identity=identity,
                        subdataset=subdataset.name,
                        reason_conflict_type=conflict_type_purity.type,
                        subdataset_purity=subdataset.purity,
                        reason_purity=conflict_type_purity.purity,
                        logical_conflict_count=tilt_info.logical_conflict_count,
                    )
                )

    return candidates


def rank_candidate(candidate: TiltCandidate) -> tuple[float, float, str, str]:
    return (
        -candidate.subdataset_purity,
        -candidate.reason_purity,
        candidate.identity.repo,
        candidate.identity.merge_sha,
    )


def select_tilt_candidates(
    candidates: list[TiltCandidate],
    *,
    targets: tuple[TiltTarget, ...],
) -> TiltPlaybookBuildResult:
    candidates_by_reason: dict[ConflictType, list[TiltCandidate]] = {
        target.conflict_type: []
        for target in targets
    }
    for candidate in candidates:
        if candidate.reason_conflict_type in candidates_by_reason:
            candidates_by_reason[candidate.reason_conflict_type].append(candidate)

    ordered_targets = sorted(
        targets,
        key=lambda target: (
            len(candidates_by_reason[target.conflict_type]) / target.count,
            len(candidates_by_reason[target.conflict_type]),
            target.conflict_type.value,
        ),
    )
    used_identities: set[TiltConflictIdentity] = set()
    selected: list[TiltCandidate] = []
    shortfalls: dict[ConflictType, int] = {}

    for target in ordered_targets:
        available = [
            candidate
            for candidate in candidates_by_reason[target.conflict_type]
            if candidate.identity not in used_identities
        ]
        available.sort(key=rank_candidate)
        target_selection = available[:target.count]

        for candidate in target_selection:
            used_identities.add(candidate.identity)
            selected.append(candidate)

        if len(target_selection) < target.count:
            shortfalls[target.conflict_type] = target.count - len(target_selection)

    return TiltPlaybookBuildResult(
        selected=sorted(selected, key=lambda candidate: (candidate.identity.repo, candidate.identity.merge_sha)),
        candidate_count=len(candidates),
        candidate_counts_by_reason={
            conflict_type: len(reason_candidates)
            for conflict_type, reason_candidates in candidates_by_reason.items()
        },
        shortfalls_by_reason=shortfalls,
    )


def build_tilt_playbook_result(
    redis=None,
    *,
    targets: tuple[TiltTarget, ...],
) -> TiltPlaybookBuildResult:
    redis = redis or setup_redis_connection()
    return select_tilt_candidates(
        collect_tilt_candidates(redis, targets=targets),
        targets=targets,
    )


def grouped_selected_candidates(selected: list[TiltCandidate]) -> dict[str, list[TiltCandidate]]:
    grouped: dict[str, list[TiltCandidate]] = {}
    for candidate in selected:
        grouped.setdefault(candidate.identity.repo, []).append(candidate)
    return grouped


def write_tilt_playbook(selected: list[TiltCandidate], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    grouped = grouped_selected_candidates(selected)

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("playbook:\n")
        handle.write("  sources:\n")
        for repo in sorted(grouped):
            handle.write(f"    - repo_url: https://github.com/{repo}\n")
            handle.write("      override_merge_shas:\n")
            for candidate in sorted(grouped[repo], key=lambda item: item.identity.merge_sha):
                handle.write(
                    f"        - {candidate.identity.merge_sha}"
                    f" # subdataset: {candidate.subdataset};"
                    f" reason: {candidate.reason_conflict_type.value};"
                    f" subdataset_purity: {candidate.subdataset_purity:.6f};"
                    f" reason_purity: {candidate.reason_purity:.6f}\n"
                )


def selected_record(candidate: TiltCandidate) -> dict:
    return {
        "dataset": DATASET_NAME,
        "conflict_identifier": candidate.identity.identifier(),
        "repo": candidate.identity.repo,
        "merge_commit_oid": candidate.identity.merge_sha,
        "subdataset": candidate.subdataset,
        "reason_conflict_type": candidate.reason_conflict_type.value,
        "subdataset_purity": candidate.subdataset_purity,
        "reason_purity": candidate.reason_purity,
        "logical_conflict_count": candidate.logical_conflict_count,
        "source_info_key": tilt_info_key(candidate.identity),
    }


def summary_record(
    result: TiltPlaybookBuildResult,
    *,
    targets: tuple[TiltTarget, ...],
) -> dict:
    subdataset_counts = Counter(candidate.subdataset for candidate in result.selected)
    reason_counts = Counter(candidate.reason_conflict_type.value for candidate in result.selected)

    return {
        "dataset": DATASET_NAME,
        "selected_count": len(result.selected),
        "candidate_count": result.candidate_count,
        "subdataset_counts": dict(sorted(subdataset_counts.items())),
        "reason_conflict_type_counts": dict(sorted(reason_counts.items())),
        "targets": [
            {
                "subdataset": target.subdataset,
                "conflict_type": target.conflict_type.value,
                "count": target.count,
            }
            for target in targets
        ],
        "shortfalls_by_reason": {
            conflict_type.value: shortfall
            for conflict_type, shortfall in sorted(
                result.shortfalls_by_reason.items(),
                key=lambda item: item[0].value,
            )
        },
    }


def prune_existing_dataset_tilt_records(redis) -> int:
    keys = list(redis.scan_iter(match=f"{DATASET_TILT_PREFIX}*"))
    if keys:
        redis.delete(*keys)
    return len(keys)


def write_dataset_tilt_records(
    redis,
    result: TiltPlaybookBuildResult,
    *,
    targets: tuple[TiltTarget, ...],
) -> int:
    prune_existing_dataset_tilt_records(redis)
    redis.json().set(DATASET_TILT_KEY, "$", summary_record(result, targets=targets))
    for candidate in result.selected:
        redis.json().set(dataset_tilt_conflict_key(candidate.identity), "$", selected_record(candidate))
    return len(result.selected)


def generate_tilt_playbook(
    output_path: Path,
    *,
    redis=None,
    targets: tuple[TiltTarget, ...],
) -> TiltPlaybookBuildResult:
    redis = redis or setup_redis_connection()
    result = build_tilt_playbook_result(redis, targets=targets)
    write_tilt_playbook(result.selected, output_path)
    write_dataset_tilt_records(redis, result, targets=targets)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create the tilt dataset playbook from info:conflict:tilt records and "
            "record selected dataset membership in Redis."
        )
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=sorted(TARGETS_BY_NAME),
        help="Named tilt target to generate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output playbook path.",
    )
    args = parser.parse_args()

    targets = targets_for_name(args.target)
    output = args.output or default_playbook_output_path(args.target)

    result = generate_tilt_playbook(output, targets=targets)

    if result.shortfalls_by_reason:
        for conflict_type, shortfall in result.shortfalls_by_reason.items():
            logger.error(
                "Target for {} is short by {} conflicts",
                conflict_type.value,
                shortfall,
            )
        return 1

    subdataset_counts = Counter(candidate.subdataset for candidate in result.selected)
    logger.info(
        "Wrote tilt playbook with {} conflicts to {}",
        len(result.selected),
        output,
    )
    for subdataset, count in sorted(subdataset_counts.items()):
        logger.info("{}: {}", subdataset, count)
    logger.info("Recorded {} selected conflicts under dataset:tilt", len(result.selected))

    return 0


if __name__ == "__main__":
    sys.exit(main())
