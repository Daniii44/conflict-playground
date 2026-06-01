import tempfile
from itertools import combinations
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from common.git_util import capture_git
from common.merge_tree import MergeResult
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from info.conflict.analysis.core_analysis import CoreAnalysis


class OctopusPairwiseConflict(BaseModel):
    parent_a_index: int
    parent_a_oid: str
    parent_b_index: int
    parent_b_oid: str
    merge_result: MergeResult


class InfoConflictOctopus(InfoConflict):
    parent_count: int
    parent_oids: list[str]
    octopus_merge_clean: bool
    octopus_merge_error: str | None
    pairwise_conflicts: list[OctopusPairwiseConflict]


class OctopusAnalysis(Analysis):
    def __init__(self, analysis_name: str):
        super().__init__(analysis_name)
        self._core_analysis = CoreAnalysis("core")

    def collect_parents(self, analysis_input: AnalysisInput) -> list[str]:
        return self._core_analysis.collect_parents(analysis_input)

    def try_octopus_merge(self, git_dir: str, parents: list[str]) -> tuple[bool, str | None]:
        with tempfile.TemporaryDirectory(prefix="octopus-analysis-") as tmp_dir:
            index_file = Path(tmp_dir) / "index"
            object_dir = Path(tmp_dir) / "objects"
            object_dir.mkdir()
            git_env = {
                "GIT_INDEX_FILE": str(index_file),
                "GIT_OBJECT_DIRECTORY": str(object_dir),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(Path(git_dir) / "objects"),
            }
            current_merge_commits = [parents[0]]
            current_merge_tree = parents[0]
            non_fast_forward_merge = False

            for parent_oid in parents[1:]:
                merge_base_result = capture_git(
                    f"--git-dir={git_dir}",
                    "merge-base",
                    "--all",
                    parent_oid,
                    *current_merge_commits,
                    check=False,
                    env=git_env,
                )
                if merge_base_result.returncode != 0:
                    return False, (merge_base_result.stdout + merge_base_result.stderr).strip() or None

                merge_bases = merge_base_result.stdout.strip().splitlines()
                if not merge_bases:
                    return False, f"Unable to find common commit with {parent_oid}"

                if parent_oid in merge_bases:
                    continue

                if (
                    len(merge_bases) == 1
                    and merge_bases[0] == current_merge_commits[0]
                    and not non_fast_forward_merge
                ):
                    current_merge_commits = [parent_oid]
                    current_merge_tree = parent_oid
                    continue

                non_fast_forward_merge = True
                if len(merge_bases) != 1:
                    return False, "Octopus merge has multiple merge bases"

                read_tree_result = capture_git(
                    f"--git-dir={git_dir}",
                    "read-tree",
                    "-i",
                    "-m",
                    "--aggressive",
                    merge_bases[0],
                    current_merge_tree,
                    parent_oid,
                    check=False,
                    env=git_env,
                )
                if read_tree_result.returncode != 0:
                    return False, (read_tree_result.stdout + read_tree_result.stderr).strip() or None

                write_tree_result = capture_git(
                    f"--git-dir={git_dir}",
                    "write-tree",
                    check=False,
                    env=git_env,
                )
                if write_tree_result.returncode != 0:
                    return False, (write_tree_result.stdout + write_tree_result.stderr).strip() or None

                current_merge_commits.append(parent_oid)
                current_merge_tree = write_tree_result.stdout.strip()

        return True, None

    def collect_pairwise_conflicts(
        self,
        git_dir: str,
        parents: list[str],
    ) -> list[OctopusPairwiseConflict]:
        pairwise_conflicts = []
        for (parent_a_index, parent_a_oid), (parent_b_index, parent_b_oid) in combinations(
            enumerate(parents, start=1),
            2,
        ):
            merge_result = self._core_analysis.collect_bare_merge_result(
                git_dir,
                parent_a_oid,
                parent_b_oid,
            )
            if merge_result is None:
                continue

            pairwise_conflicts.append(
                OctopusPairwiseConflict(
                    parent_a_index=parent_a_index,
                    parent_a_oid=parent_a_oid,
                    parent_b_index=parent_b_index,
                    parent_b_oid=parent_b_oid,
                    merge_result=merge_result,
                )
            )

        return pairwise_conflicts

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parents = self.collect_parents(analysis_input)
        if len(parents) <= 2:
            return None

        octopus_merge_clean, octopus_merge_error = self.try_octopus_merge(
            analysis_input.git_dir,
            parents,
        )
        pairwise_conflicts = []
        if not octopus_merge_clean:
            logger.debug(
                "Octopus merge attempt for {} failed; checking pairwise parent conflicts",
                analysis_input.merge_commit_oid,
            )
            pairwise_conflicts = self.collect_pairwise_conflicts(
                analysis_input.git_dir,
                parents,
            )

        return (
            analysis_input,
            InfoConflictOctopus(
                repo=analysis_input.git_repo_name,
                merge_commit_oid=analysis_input.merge_commit_oid,
                parent_count=len(parents),
                parent_oids=parents,
                octopus_merge_clean=octopus_merge_clean,
                octopus_merge_error=octopus_merge_error,
                pairwise_conflicts=pairwise_conflicts,
            ),
        )
