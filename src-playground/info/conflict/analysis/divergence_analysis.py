import subprocess
from pydantic import BaseModel
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict


class InfoConflictDivergence(InfoConflict):
    parent_count: int
    merge_base_count: int
    entangled_commit_count: int | None  # None if parent_count != 2


class DivergenceAnalysis(Analysis):
    def collect_parents(self, analysisInput: AnalysisInput) -> list[str]:
        revparse_cmd = ["git", f"--git-dir={analysisInput.git_dir}", "rev-parse", f"{analysisInput.merge_commit_oid}^@"]
        return subprocess.check_output(revparse_cmd, text=True).strip().split()

    def analyse(self, analysisInput: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parents = self.collect_parents(analysisInput)

        merge_base_cmd = ["git", f"--git-dir={analysisInput.git_dir}", "merge-base", "-a"] + parents
        merge_bases = subprocess.check_output(merge_base_cmd, text=True).strip().split()

        entangled_commit_count = None
        if len(parents) == 2:
            rev_list_cmd = ["git", f"--git-dir={analysisInput.git_dir}", "rev-list", "--count", f"{parents[0]}...{parents[1]}"]
            entangled_commit_count = int(subprocess.check_output(rev_list_cmd, text=True))

        return (
            analysisInput,
            InfoConflictDivergence(
                repo=analysisInput.git_repo_name,
                merge_commit_oid=analysisInput.merge_commit_oid,
                parent_count=len(parents),
                merge_base_count=len(merge_bases),
                entangled_commit_count=entangled_commit_count,
            )
        )