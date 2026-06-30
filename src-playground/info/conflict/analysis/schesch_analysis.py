import os
import shutil
import subprocess
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from common.evaluation_models import ScheschResolutionResult
from common.git_util import capture_git
from common.schesch import DEFAULT_TIMEOUT_SECONDS, ScheschResolutionRunner
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from playground.setup import playground_name, setup_playground


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

    def playground_path(self, analysis_input: AnalysisInput) -> Path:
        playgrounds = Path(os.environ.get("PLAYGROUNDS", str(Path.home() / "playgrounds")))
        return playgrounds / playground_name(analysis_input.git_repo_name, analysis_input.merge_commit_oid)

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parent_shas = self.collect_parents(analysis_input)
        if len(parent_shas) != 2:
            return self.failed(
                analysis_input,
                parent_shas,
                f"Expected exactly 2 parents, found {len(parent_shas)}",
            )

        worktree_path = self.playground_path(analysis_input)
        try:
            setup_playground(analysis_input.git_repo_name, analysis_input.merge_commit_oid)

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
        except (RuntimeError, subprocess.CalledProcessError) as error:
            return self.failed(analysis_input, parent_shas, f"Could not setup analysis playground: {error}")
        finally:
            shutil.rmtree(worktree_path, ignore_errors=True)
