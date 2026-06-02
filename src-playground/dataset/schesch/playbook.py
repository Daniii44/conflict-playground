#!/usr/bin/env python3

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

from loguru import logger

from dataset.schesch.count import default_merge_analysis_path, iter_qualifying_merge_pairs


def default_playbook_output_path() -> Path:
    playbooks_env = os.environ.get("PLAYBOOKS")
    if playbooks_env:
        return Path(playbooks_env) / "schesch.yaml"

    local_playbooks = Path.cwd() / "data" / "playbooks"
    if local_playbooks.exists():
        return local_playbooks / "schesch.yaml"

    return Path("/root/playbooks/schesch.yaml")


def build_schesch_playbook(merge_analysis: Path) -> dict:
    merges_by_repo: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for merge_pair in iter_qualifying_merge_pairs(merge_analysis):
        merges_by_repo[merge_pair.repo].add((merge_pair.left_parent, merge_pair.right_parent))

    sources = []
    for repo in sorted(merges_by_repo):
        parent_pairs = sorted(merges_by_repo[repo])
        sources.append(
            {
                "repo_url": f"https://github.com/{repo}.git",
                "override_merge_shas": [
                    {"parents": [left_parent, right_parent]}
                    for left_parent, right_parent in parent_pairs
                ],
            }
        )

    return {"playbook": {"sources": sources}}


def write_playbook(playbook: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("playbook:\n")
        handle.write("  sources:\n")
        for source in playbook["playbook"]["sources"]:
            handle.write(f"    - repo_url: {source['repo_url']}\n")
            handle.write("      override_merge_shas:\n")
            for override in source["override_merge_shas"]:
                left_parent, right_parent = override["parents"]
                handle.write("        - parents:\n")
                handle.write(f"            - {left_parent}\n")
                handle.write(f"            - {right_parent}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a playbook for the retained Schesch merge_analysis subset. "
            "The playbook uses parent-pair override_merge_shas entries because "
            "merge_analysis does not contain the merge commit SHA."
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

    playbook = build_schesch_playbook(args.merge_analysis)
    sources = playbook["playbook"]["sources"]
    merge_count = sum(len(source["override_merge_shas"]) for source in sources)

    write_playbook(playbook, args.output)
    logger.info(
        "Wrote Schesch playbook with {} repositories and {} parent-pair overrides to {}",
        len(sources),
        merge_count,
        args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
