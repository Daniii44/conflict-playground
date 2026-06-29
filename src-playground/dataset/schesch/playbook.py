#!/usr/bin/env python3

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from dataset.schesch.count import default_merge_analysis_path, iter_qualifying_merge_pairs
from dataset.schesch.merge_lookup import group_merge_pairs_by_repo, merge_parent_index


@dataclass(frozen=True)
class PlaybookBuildResult:
    playbook: dict
    unresolved_parent_pairs: int
    ambiguous_parent_pairs: int
    skipped_repos: set[str]


def default_playbook_output_path() -> Path:
    playbooks_env = os.environ.get("PLAYBOOKS")
    if playbooks_env:
        return Path(playbooks_env) / "schesch.yaml"

    local_playbooks = Path.cwd() / "data" / "playbooks"
    if local_playbooks.exists():
        return local_playbooks / "schesch.yaml"

    return Path("/root/playbooks/schesch.yaml")


def build_schesch_playbook_result(merge_analysis: Path) -> PlaybookBuildResult:
    merges_by_repo = group_merge_pairs_by_repo(list(iter_qualifying_merge_pairs(merge_analysis)))
    unresolved_parent_pairs = 0
    ambiguous_parent_pairs = 0
    skipped_repos: set[str] = set()

    sources = []
    for repo in sorted(merges_by_repo):
        try:
            index = merge_parent_index(repo)
        except RuntimeError as error:
            logger.error("Skipping {}: {}", repo, error)
            skipped_repos.add(repo)
            continue

        merge_shas = []
        for left_parent, right_parent in sorted(merges_by_repo[repo]):
            matches = index.get(frozenset((left_parent, right_parent)), [])
            if not matches:
                logger.warning(
                    "{}: no merge commit found for parents {} and {}",
                    repo,
                    left_parent,
                    right_parent,
                )
                unresolved_parent_pairs += 1
                continue

            if len(matches) > 1:
                logger.warning(
                    "{}: pruning parent pair {} and {} because it resolves to {} merge commits",
                    repo,
                    left_parent,
                    right_parent,
                    len(matches),
                )
                ambiguous_parent_pairs += 1
                continue

            merge_shas.append(matches[0])

        if not merge_shas:
            continue

        sources.append(
            {
                "repo_url": f"https://github.com/{repo}",
                "override_merge_shas": merge_shas,
            }
        )

    return PlaybookBuildResult(
        playbook={"playbook": {"sources": sources}},
        unresolved_parent_pairs=unresolved_parent_pairs,
        ambiguous_parent_pairs=ambiguous_parent_pairs,
        skipped_repos=skipped_repos,
    )


def build_schesch_playbook(merge_analysis: Path) -> dict:
    return build_schesch_playbook_result(merge_analysis).playbook


def write_playbook(playbook: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("playbook:\n")
        handle.write("  sources:\n")
        for source in playbook["playbook"]["sources"]:
            handle.write(f"    - repo_url: {source['repo_url']}\n")
            handle.write("      override_merge_shas:\n")
            for merge_sha in source["override_merge_shas"]:
                handle.write(f"        - {merge_sha}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a playbook for the retained Schesch merge_analysis subset. "
            "Merge commits are resolved from parent pairs using cached bare repositories."
        )
    )
    parser.add_argument(
        "--merge-analysis",
        type=Path,
        default=default_merge_analysis_path(),
        help="Path to data/datasets/schesch/merge_analysis.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_playbook_output_path(),
        help="Output playbook path.",
    )
    args = parser.parse_args()

    if not args.merge_analysis.is_dir():
        parser.error(f"merge_analysis directory does not exist: {args.merge_analysis}")

    result = build_schesch_playbook_result(args.merge_analysis)
    playbook = result.playbook
    sources = playbook["playbook"]["sources"]
    merge_count = sum(len(source["override_merge_shas"]) for source in sources)

    write_playbook(playbook, args.output)
    logger.info(
        "Wrote Schesch playbook with {} repositories and {} merge overrides to {}",
        len(sources),
        merge_count,
        args.output,
    )
    if result.unresolved_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that could not be resolved to a merge commit",
            result.unresolved_parent_pairs,
        )
    if result.ambiguous_parent_pairs:
        logger.warning(
            "Pruned {} parent pairs that resolved to multiple merge commits",
            result.ambiguous_parent_pairs,
        )
    if result.skipped_repos:
        logger.error(
            "Skipped {} repositories because their cached bare repository was missing or inaccessible",
            len(result.skipped_repos),
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
