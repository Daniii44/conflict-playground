import subprocess
from pydantic import BaseModel
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict


def _diff_name_status(git_dir: str, base: str, ref: str) -> str:
    cmd = ["git", f"--git-dir={git_dir}", "diff-tree", "-r", "--name-status", "-M", base, ref]
    return subprocess.check_output(cmd, text=True)


def _parse_name_status(output: str) -> tuple[set, set, set, dict]:
    modified, added, deleted, renames = set(), set(), set(), {}
    for line in output.strip().splitlines():
        if not line:
            continue
        parts = line.split('\t')
        status = parts[0]
        if status in ('M', 'T'):
            modified.add(parts[1])
        elif status == 'A':
            added.add(parts[1])
        elif status == 'D':
            deleted.add(parts[1])
        elif status[0] == 'R':
            renames[parts[1]] = parts[2]
        elif status[0] == 'C':
            added.add(parts[2])
    return modified, added, deleted, renames


class InfoConflictTreeDiff(InfoConflict):
    # File overlap (None for octopus merges)
    files_modified_overlap: int | None
    files_added_overlap: int | None
    files_deleted_modified_overlap: int | None
    # Rename conflicts (None for octopus merges)
    rename_edit_conflicts: int | None
    rename_rename_conflicts: int | None


class TreeDiffAnalysis(Analysis):
    def _get_parents(self, git_dir: str, merge_commit: str) -> list[str]:
        cmd = ["git", f"--git-dir={git_dir}", "rev-parse", f"{merge_commit}^@"]
        return subprocess.check_output(cmd, text=True).strip().split()

    def _get_merge_base(self, git_dir: str, parents: list[str]) -> str | None:
        cmd = ["git", f"--git-dir={git_dir}", "merge-base", "-a"] + parents
        try:
            bases = subprocess.check_output(cmd, text=True).strip().split()
            return bases[0] if bases else None
        except subprocess.CalledProcessError:
            return None

    def analyse(self, analysisInput: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        git_dir = analysisInput.git_dir
        parents = self._get_parents(git_dir, analysisInput.merge_commit_oid)
        base = self._get_merge_base(git_dir, parents)
        if base is None:
            return None

        diffs = [_parse_name_status(_diff_name_status(git_dir, base, p)) for p in parents]
        is_binary = len(parents) == 2

        if is_binary:
            mod0, add0, del0, ren0 = diffs[0]
            mod1, add1, del1, ren1 = diffs[1]
            files_modified_overlap = len(mod0 & mod1)
            files_added_overlap = len(add0 & add1)
            files_deleted_modified_overlap = len((del0 & mod1) | (del1 & mod0))
            # renamed in one parent, modified in the other
            rename_edit_conflicts = len((set(ren0) & mod1) | (set(ren1) & mod0))
            # same source renamed in both, or different sources renamed to the same target
            rename_rename_conflicts = len(set(ren0) & set(ren1)) + len(set(ren0.values()) & set(ren1.values()))
        else:
            files_modified_overlap = None
            files_added_overlap = None
            files_deleted_modified_overlap = None
            rename_edit_conflicts = None
            rename_rename_conflicts = None

        return (
            analysisInput,
            InfoConflictTreeDiff(
                repo=analysisInput.git_repo_name,
                merge_commit_oid=analysisInput.merge_commit_oid,
                files_modified_overlap=files_modified_overlap,
                files_added_overlap=files_added_overlap,
                files_deleted_modified_overlap=files_deleted_modified_overlap,
                rename_edit_conflicts=rename_edit_conflicts,
                rename_rename_conflicts=rename_rename_conflicts,
            )
        )
