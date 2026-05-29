import os
import shutil
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from common.git_util import capture_git
from common.merge_tree import ConflictType, MergeResult, parse_merge_result, prune_auto_merged
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from playground.setup import playground_name, setup_playground


SUBMODULE_CONFLICT_TYPES = {
    ConflictType.CONFLICT_SUBMODULE_FAILED_TO_MERGE,
    ConflictType.CONFLICT_SUBMODULE_FAILED_TO_MERGE_BUT_POSSIBLE_RESOLUTION,
    ConflictType.CONFLICT_SUBMODULE_NOT_INITIALIZED,
    ConflictType.CONFLICT_SUBMODULE_HISTORY_NOT_AVAILABLE,
    ConflictType.CONFLICT_SUBMODULE_MAY_HAVE_REWINDS,
    ConflictType.CONFLICT_SUBMODULE_NULL_MERGE_BASE,
    ConflictType.ERROR_SUBMODULE_CORRUPT,
}


class InfoConflictSubmodule(InfoConflict):
    merge_result: MergeResult


class SubmoduleAnalysis(Analysis):
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

    def process_merge_tree_output(
        self,
        repo_path: Path,
        main_ref: str,
        feature_ref: str,
    ) -> MergeResult | None:
        result = capture_git(
            "-C",
            str(repo_path),
            "merge-tree",
            "-z",
            "--messages",
            main_ref,
            feature_ref,
            check=False,
        )

        output = result.stdout.encode()
        stderr = result.stderr.encode()
        if b"fatal: refusing to merge unrelated histories" in output + stderr:
            return None

        return prune_auto_merged(parse_merge_result(output))

    def has_submodule_conflict(self, merge_result: MergeResult) -> bool:
        return any(
            conflict.type in SUBMODULE_CONFLICT_TYPES
            for conflict in merge_result.logical_conflicts
        )

    def collect_bare_merge_result(
        self,
        analysis_input: AnalysisInput,
        main_oid: str,
        feature_oid: str,
    ) -> MergeResult | None:
        result = capture_git(
            f"--git-dir={analysis_input.git_dir}",
            "merge-tree",
            "-z",
            main_oid,
            feature_oid,
            check=False,
        )
        if result.returncode == 0:
            return None

        output = result.stdout.encode()
        stderr = result.stderr.encode()
        if b"fatal: refusing to merge unrelated histories" in output + stderr:
            return None

        return prune_auto_merged(parse_merge_result(output))

    def analyse(self, analysisInput: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parents = self.collect_parents(analysisInput)
        if len(parents) < 2:
            logger.error(
                "Merge commit {} has less than 2 parents, skipping",
                analysisInput.merge_commit_oid,
            )
            return None
        if len(parents) > 2:
            logger.info(
                "Merge commit {} has more than 2 parents, skipping",
                analysisInput.merge_commit_oid,
            )
            return None

        bare_merge_result = self.collect_bare_merge_result(analysisInput, parents[1], parents[0])
        if bare_merge_result is None or not self.has_submodule_conflict(bare_merge_result):
            return None

        playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
        playground_path = playgrounds / playground_name(
            analysisInput.git_repo_name,
            analysisInput.merge_commit_oid,
        )
        try:
            setup_playground(analysisInput.git_repo_name, analysisInput.merge_commit_oid)
            merge_result = self.process_merge_tree_output(playground_path, "main", "feature")
            if merge_result is None:
                return None

            return (
                analysisInput,
                InfoConflictSubmodule(
                    repo=analysisInput.git_repo_name,
                    merge_commit_oid=analysisInput.merge_commit_oid,
                    merge_result=merge_result,
                ),
            )
        finally:
            shutil.rmtree(playground_path, ignore_errors=True)
