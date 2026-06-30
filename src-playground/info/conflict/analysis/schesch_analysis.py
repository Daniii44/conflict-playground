import shutil
import tempfile
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from common.evaluation_models import ScheschResolutionResult
from common.git_util import capture_git
from common.schesch import DEFAULT_TIMEOUT_SECONDS, ScheschResolutionRunner
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict


class InfoConflictSchesch(InfoConflict):
    actual_resolution_sha: str
    parent_shas: list[str] = Field(default_factory=list)
    timeout_seconds: int
    human: ScheschResolutionResult | None = None
    parents: list[ScheschResolutionResult] = Field(default_factory=list)
    error: str | None = None


class ScheschInfoAnalysis(Analysis, ScheschResolutionRunner):
    def __init__(self, analysis_name: str = "schesch", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        Analysis.__init__(self, analysis_name)
        ScheschResolutionRunner.__init__(self, timeout_seconds)

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

    def clone_worktree(self, git_dir: str, worktree_path: Path) -> str | None:
        result = capture_git(
            "clone",
            "--shared",
            git_dir,
            str(worktree_path),
            check=False,
        )
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip()
        return None

    def failed(
        self,
        analysis_input: AnalysisInput,
        parent_shas: list[str],
        error: str,
    ) -> tuple[AnalysisInput, BaseModel]:
        return (
            analysis_input,
            InfoConflictSchesch(
                repo=analysis_input.git_repo_name,
                merge_commit_oid=analysis_input.merge_commit_oid,
                actual_resolution_sha=analysis_input.merge_commit_oid,
                parent_shas=parent_shas,
                timeout_seconds=self.timeout_seconds,
                error=error,
            ),
        )

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parent_shas = self.collect_parents(analysis_input)
        if len(parent_shas) != 2:
            return self.failed(
                analysis_input,
                parent_shas,
                f"Expected exactly 2 parents, found {len(parent_shas)}",
            )

        worktree_path = None
        try:
            worktree_path = Path(tempfile.mkdtemp(prefix="schesch-info-"))
            clone_error = self.clone_worktree(analysis_input.git_dir, worktree_path)
            if clone_error is not None:
                return self.failed(analysis_input, parent_shas, f"Could not clone analysis worktree: {clone_error}")

            human = self.run_tests_for_ref(
                worktree_path,
                analysis_input.merge_commit_oid,
                "human",
                analysis_input.merge_commit_oid,
            )
            parent_results = [
                self.run_tests_for_ref(worktree_path, parent_sha, f"parent-{index}", parent_sha)
                for index, parent_sha in enumerate(parent_shas, start=1)
            ]

            return (
                analysis_input,
                InfoConflictSchesch(
                    repo=analysis_input.git_repo_name,
                    merge_commit_oid=analysis_input.merge_commit_oid,
                    actual_resolution_sha=analysis_input.merge_commit_oid,
                    parent_shas=parent_shas,
                    timeout_seconds=self.timeout_seconds,
                    human=human,
                    parents=parent_results,
                ),
            )
        finally:
            if worktree_path is not None:
                shutil.rmtree(worktree_path, ignore_errors=True)
