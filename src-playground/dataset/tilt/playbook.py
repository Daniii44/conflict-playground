#!/usr/bin/env python3

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path

from loguru import logger

from common.merge_tree import ConflictType
from common.redis_util import setup_redis_connection
from info.conflict.analysis.tilt_analysis import InfoConflictTilt


DATASET_NAME = "tilt"
DATASET_TILT_KEY = "dataset:tilt"
DATASET_TILT_PREFIX = "dataset:tilt:"
INFO_TILT_PREFIX = "info:conflict:tilt:"
REPO_DIVERSITY_PENALTY = 0.005


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


TOP200_TARGETS: tuple[TiltTarget, ...] = (
    TiltTarget("content", ConflictType.CONFLICT_CONTENTS, 300),
    TiltTarget("content", ConflictType.CONFLICT_BINARY, 34),
    TiltTarget("modify/delete", ConflictType.CONFLICT_MODIFY_DELETE, 333),
    TiltTarget("rename", ConflictType.CONFLICT_RENAME_DELETE, 102),
    TiltTarget("rename", ConflictType.CONFLICT_RENAME_RENAME, 59),
    TiltTarget("rename", ConflictType.CONFLICT_DIR_RENAME_SUGGESTED, 151),
    TiltTarget("rename", ConflictType.CONFLICT_DIR_RENAME_SPLIT, 21),
)

TARGETS_BY_NAME: dict[str, tuple[TiltTarget, ...]] = {
    "top200": TOP200_TARGETS,
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
    verbose: bool = False,
) -> list[TiltCandidate]:
    targets_by_type = target_by_conflict_type(targets)
    candidates: list[TiltCandidate] = []
    scanned_records = 0
    malformed_keys = 0
    missing_records = 0

    for key in sorted(redis.scan_iter(match=f"{INFO_TILT_PREFIX}*")):
        scanned_records += 1
        identity = parse_tilt_info_key(key)
        if identity is None:
            malformed_keys += 1
            logger.warning("Skipping malformed tilt info key: {}", key)
            continue

        data = redis.json().get(key)
        if data is None:
            missing_records += 1
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

    if verbose:
        log_candidate_collection_summary(
            candidates,
            targets=targets,
            scanned_records=scanned_records,
            malformed_keys=malformed_keys,
            missing_records=missing_records,
        )

    return candidates


def rank_candidate(candidate: TiltCandidate) -> tuple[float, float, str]:
    return (
        -candidate.subdataset_purity,
        -candidate.reason_purity,
        candidate.identity.merge_sha,
    )


def diversified_candidate_rank(
    candidate: TiltCandidate,
    selected_repo_counts: Counter[str],
) -> tuple[float, float, int, str, str]:
    repo_selected_count = selected_repo_counts[candidate.identity.repo]
    repo_penalty = repo_selected_count * REPO_DIVERSITY_PENALTY
    return (
        -(candidate.subdataset_purity - repo_penalty),
        -(candidate.reason_purity - repo_penalty),
        repo_selected_count,
        candidate.identity.repo,
        candidate.identity.merge_sha,
    )


def select_diversified_candidates(
    candidates: list[TiltCandidate],
    *,
    count: int,
    selected_repo_counts: Counter[str],
) -> list[TiltCandidate]:
    remaining = list(candidates)
    selected: list[TiltCandidate] = []

    while remaining and len(selected) < count:
        candidate = min(
            remaining,
            key=lambda item: diversified_candidate_rank(item, selected_repo_counts),
        )
        remaining.remove(candidate)
        selected_repo_counts[candidate.identity.repo] += 1
        selected.append(candidate)

    return selected


def target_label(target: TiltTarget) -> str:
    return f"{target.subdataset} / {target.conflict_type.value}"


def format_counter(counter: Counter, *, limit: int = 8) -> str:
    if not counter:
        return "none"

    parts = [
        f"{label}={count}"
        for label, count in counter.most_common(limit)
    ]
    remaining = len(counter) - limit
    if remaining > 0:
        parts.append(f"... {remaining} more")
    return ", ".join(parts)


def log_candidate_collection_summary(
    candidates: list[TiltCandidate],
    *,
    targets: tuple[TiltTarget, ...],
    scanned_records: int,
    malformed_keys: int,
    missing_records: int,
) -> None:
    unique_identities = {candidate.identity for candidate in candidates}
    logger.info(
        "TILT candidate collection: scanned {} info records, collected {} target-matching rows across {} unique merge identities",
        scanned_records,
        len(candidates),
        len(unique_identities),
    )
    if malformed_keys or missing_records:
        logger.info(
            "TILT candidate collection skipped {} malformed keys and {} missing JSON records",
            malformed_keys,
            missing_records,
        )

    repo_counts = Counter(candidate.identity.repo for candidate in candidates)
    logger.info("TILT candidate repositories: {}", format_counter(repo_counts))

    for target in targets:
        target_candidates = [
            candidate
            for candidate in candidates
            if candidate.subdataset == target.subdataset
            and candidate.reason_conflict_type == target.conflict_type
        ]
        target_unique_identities = {candidate.identity for candidate in target_candidates}
        target_repo_counts = Counter(candidate.identity.repo for candidate in target_candidates)
        logger.info(
            "Candidate pool for {}: target={}, rows={}, unique_merge_identities={}, duplicate_rows={}, repos={}",
            target_label(target),
            target.count,
            len(target_candidates),
            len(target_unique_identities),
            len(target_candidates) - len(target_unique_identities),
            format_counter(target_repo_counts),
        )


def overlap_aware_target_order(
    targets: tuple[TiltTarget, ...],
    *,
    candidates_by_reason: dict[ConflictType, list[TiltCandidate]],
) -> list[TiltTarget]:
    target_identities = {
        target: {
            candidate.identity
            for candidate in candidates_by_reason[target.conflict_type]
        }
        for target in targets
    }
    identity_target_counts = Counter(
        identity
        for identities in target_identities.values()
        for identity in identities
    )

    def order_key(target: TiltTarget) -> tuple[bool, float, float, float, int, str]:
        identities = target_identities[target]
        unique_count = len(identities)
        exclusive_count = sum(
            1
            for identity in identities
            if identity_target_counts[identity] == 1
        )
        shared_count = unique_count - exclusive_count

        return (
            exclusive_count >= target.count,
            exclusive_count / target.count,
            unique_count / target.count,
            -(shared_count / unique_count) if unique_count else 0.0,
            unique_count,
            target.conflict_type.value,
        )

    return sorted(targets, key=order_key)


def simulate_shortfalls_for_order(
    ordered_targets: tuple[TiltTarget, ...],
    *,
    ranked_candidates_by_reason: dict[ConflictType, list[TiltCandidate]],
) -> dict[ConflictType, int]:
    used_identities: set[TiltConflictIdentity] = set()
    shortfalls: dict[ConflictType, int] = {}

    for target in ordered_targets:
        selected_count = 0
        for candidate in ranked_candidates_by_reason[target.conflict_type]:
            if candidate.identity in used_identities:
                continue

            used_identities.add(candidate.identity)
            selected_count += 1
            if selected_count == target.count:
                break

        if selected_count < target.count:
            shortfalls[target.conflict_type] = target.count - selected_count

    return shortfalls


def order_tilt_targets(
    targets: tuple[TiltTarget, ...],
    *,
    candidates_by_reason: dict[ConflictType, list[TiltCandidate]],
) -> list[TiltTarget]:
    base_order = overlap_aware_target_order(
        targets,
        candidates_by_reason=candidates_by_reason,
    )
    if len(base_order) > 8:
        return base_order

    base_position = {
        target: index
        for index, target in enumerate(base_order)
    }
    ranked_candidates_by_reason = {
        conflict_type: sorted(reason_candidates, key=rank_candidate)
        for conflict_type, reason_candidates in candidates_by_reason.items()
    }

    def order_score(ordered_targets: tuple[TiltTarget, ...]) -> tuple[int, int, tuple[int, ...]]:
        shortfalls = simulate_shortfalls_for_order(
            ordered_targets,
            ranked_candidates_by_reason=ranked_candidates_by_reason,
        )
        return (
            sum(shortfalls.values()),
            len(shortfalls),
            tuple(base_position[target] for target in ordered_targets),
        )

    return list(min(permutations(base_order), key=order_score))


def log_target_order_diagnostics(
    ordered_targets: list[TiltTarget],
    *,
    candidates_by_reason: dict[ConflictType, list[TiltCandidate]],
) -> None:
    target_identities = {
        target: {
            candidate.identity
            for candidate in candidates_by_reason[target.conflict_type]
        }
        for target in ordered_targets
    }
    identity_target_counts = Counter(
        identity
        for identities in target_identities.values()
        for identity in identities
    )

    logger.info(
        "TILT selection order: {}",
        " -> ".join(target_label(target) for target in ordered_targets),
    )
    for target in ordered_targets:
        identities = target_identities[target]
        unique_count = len(identities)
        exclusive_count = sum(
            1
            for identity in identities
            if identity_target_counts[identity] == 1
        )
        shared_count = unique_count - exclusive_count
        logger.info(
            "Order metrics for {}: target={}, unique_merge_identities={}, exclusive_merge_identities={}, shared_merge_identities={}, exclusive_shortfall={}",
            target_label(target),
            target.count,
            unique_count,
            exclusive_count,
            shared_count,
            max(0, target.count - exclusive_count),
        )


def select_tilt_candidates(
    candidates: list[TiltCandidate],
    *,
    targets: tuple[TiltTarget, ...],
    verbose: bool = False,
) -> TiltPlaybookBuildResult:
    candidates_by_reason: dict[ConflictType, list[TiltCandidate]] = {
        target.conflict_type: []
        for target in targets
    }
    for candidate in candidates:
        if candidate.reason_conflict_type in candidates_by_reason:
            candidates_by_reason[candidate.reason_conflict_type].append(candidate)

    ordered_targets = order_tilt_targets(
        targets,
        candidates_by_reason=candidates_by_reason,
    )
    used_identities: set[TiltConflictIdentity] = set()
    selected_target_by_identity: dict[TiltConflictIdentity, TiltTarget] = {}
    selected_repo_counts: Counter[str] = Counter()
    selected: list[TiltCandidate] = []
    shortfalls: dict[ConflictType, int] = {}

    if verbose:
        log_target_order_diagnostics(
            ordered_targets,
            candidates_by_reason=candidates_by_reason,
        )

    for target in ordered_targets:
        target_candidates = candidates_by_reason[target.conflict_type]
        available = [
            candidate
            for candidate in target_candidates
            if candidate.identity not in used_identities
        ]
        blocked = [
            candidate
            for candidate in target_candidates
            if candidate.identity in used_identities
        ]
        target_selection = select_diversified_candidates(
            available,
            count=target.count,
            selected_repo_counts=selected_repo_counts,
        )

        for candidate in target_selection:
            used_identities.add(candidate.identity)
            selected_target_by_identity[candidate.identity] = target
            selected.append(candidate)

        if verbose:
            target_unique_identities = {candidate.identity for candidate in target_candidates}
            blocked_unique_identities = {candidate.identity for candidate in blocked}
            available_unique_identities = {candidate.identity for candidate in available}
            blocked_by_target = Counter(
                target_label(selected_target_by_identity[candidate.identity])
                for candidate in blocked
                if candidate.identity in selected_target_by_identity
            )
            logger.info(
                "Selection for {}: target={}, rows={}, unique_merge_identities={}, blocked_rows={}, blocked_unique_merge_identities={}, available_rows={}, available_unique_merge_identities={}, selected={}",
                target_label(target),
                target.count,
                len(target_candidates),
                len(target_unique_identities),
                len(blocked),
                len(blocked_unique_identities),
                len(available),
                len(available_unique_identities),
                len(target_selection),
            )
            if blocked_by_target:
                logger.info(
                    "Selection for {} overlaps already selected by: {}",
                    target_label(target),
                    format_counter(blocked_by_target),
                )

        if len(target_selection) < target.count:
            shortfalls[target.conflict_type] = target.count - len(target_selection)
            if verbose:
                logger.info(
                    "Shortfall for {}: needed {}, selected {}, short by {}; raw rows before identity de-duplication were {}",
                    target_label(target),
                    target.count,
                    len(target_selection),
                    target.count - len(target_selection),
                    len(target_candidates),
                )

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
    verbose: bool = False,
) -> TiltPlaybookBuildResult:
    redis = redis or setup_redis_connection()
    return select_tilt_candidates(
        collect_tilt_candidates(redis, targets=targets, verbose=verbose),
        targets=targets,
        verbose=verbose,
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
    verbose: bool = False,
) -> TiltPlaybookBuildResult:
    redis = redis or setup_redis_connection()
    result = build_tilt_playbook_result(redis, targets=targets, verbose=verbose)
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log candidate composition and target selection diagnostics.",
    )
    args = parser.parse_args()

    targets = targets_for_name(args.target)
    output = args.output or default_playbook_output_path(args.target)

    result = generate_tilt_playbook(output, targets=targets, verbose=args.verbose)

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
