import os
import shutil
from pathlib import Path

from common.merge_tree import ConflictType, MergeResult, parse_merge_result, prune_auto_merged
from common.git_util import capture_git
from loguru import logger
from pydantic import BaseModel

from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from playground.setup import playground_name, setup_playground


class InfoConflictCore(InfoConflict):
    merge_result: MergeResult


class CoreAnalysis(Analysis):

    def collect_parents(self, analysis_input: AnalysisInput) -> list[str]:
        result = capture_git(
            f"--git-dir={analysis_input.git_dir}",
            "show",
            "--no-patch",
            "--format=%P",
            analysis_input.merge_commit_oid,
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                "Error running git show for {}: {}",
                analysis_input.merge_commit_oid,
                result.stderr.strip(),
            )
            return []
        return result.stdout.strip().split()

    def collect_bare_merge_result(
        self,
        git_dir: str,
        main_oid: str,
        feature_oid: str,
    ) -> MergeResult | None:
        result = capture_git(
            f"--git-dir={git_dir}",
            "merge-tree",
            "-z",
            main_oid,
            feature_oid,
            check=False,
        )
        if result.returncode == 0:
            logger.debug("No conflict for merge {} and {}", main_oid, feature_oid)
            return None

        output = result.stdout.encode()
        stderr = result.stderr.encode()
        if b"fatal: refusing to merge unrelated histories" in output + stderr:
            return None

        return prune_auto_merged(parse_merge_result(output))

    def collect_playground_merge_result(self, playground_path: Path) -> MergeResult | None:
        result = capture_git(
            "-C",
            str(playground_path),
            "merge-tree",
            "-z",
            "--messages",
            "main",
            "feature",
            check=False,
        )

        output = result.stdout.encode()
        stderr = result.stderr.encode()
        if b"fatal: refusing to merge unrelated histories" in output + stderr:
            return None

        return prune_auto_merged(parse_merge_result(output))

    def needs_playground_merge_result(self, merge_result: MergeResult) -> bool:
        return any(
            conflict.type == ConflictType.CONFLICT_SUBMODULE_NOT_INITIALIZED
            for conflict in merge_result.logical_conflicts
        )

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parents = self.collect_parents(analysis_input)
        if len(parents) < 2:
            logger.error(
                "Merge commit {} has less than 2 parents, skipping",
                analysis_input.merge_commit_oid,
            )
            return None
        if len(parents) > 2:
            # Not supporting octopus merges for now, since git doesn't even allow to perform non trivial octopus merges directly.
            # TODO: Take a look whether there are complex octoopus merges nonetheless
            logger.info(
                "Merge commit {} has more than 2 parents, skipping",
                analysis_input.merge_commit_oid,
            )
            return None

        merge_result = self.collect_bare_merge_result(
            analysis_input.git_dir,
            parents[0],
            parents[1],
        )
        if merge_result is None:
            return None

        if self.needs_playground_merge_result(merge_result):
            playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
            playground_path = playgrounds / playground_name(
                analysis_input.git_repo_name,
                analysis_input.merge_commit_oid,
            )
            try:
                setup_playground(
                    analysis_input.git_repo_name,
                    analysis_input.merge_commit_oid,
                )
                merge_result = self.collect_playground_merge_result(playground_path)
            finally:
                shutil.rmtree(playground_path, ignore_errors=True)

        if merge_result is None:
            return None

        return (analysis_input, InfoConflictCore(
            repo=analysis_input.git_repo_name,
            merge_commit_oid=analysis_input.merge_commit_oid,
            merge_result=merge_result,
        ))
