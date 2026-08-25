from common.merge_tree import ConflictType, MergeConflictedFile, MergeLogicalConflict, MergeResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.core_analysis import InfoConflictCore
from info.conflict.analysis.modifydelete_analysis import (
    InfoConflictModifyDelete,
    ModifyDeleteInfoAnalysis,
)


def test_modifydelete_info_extracts_stage_oids_for_each_conflicting_path():
    core_conflict = InfoConflictCore(
        repo="owner/repo.git",
        merge_commit_oid="merge-sha",
        merge_result=MergeResult(
            result_tree_oid="conflicted-tree",
            conflicted_files=[
                MergeConflictedFile(mode="100644", oid="base", stage=1, path="deleted-by-theirs.txt"),
                MergeConflictedFile(mode="100644", oid="ours", stage=2, path="deleted-by-theirs.txt"),
                MergeConflictedFile(mode="100644", oid="base-2", stage=1, path="deleted-by-ours.txt"),
                MergeConflictedFile(mode="100644", oid="theirs", stage=3, path="deleted-by-ours.txt"),
            ],
            logical_conflicts=[
                MergeLogicalConflict(
                    type=ConflictType.CONFLICT_MODIFY_DELETE,
                    info="modify/delete",
                    paths=["deleted-by-theirs.txt", "deleted-by-ours.txt"],
                ),
            ],
        ),
    )
    analysis = ModifyDeleteInfoAnalysis("modifydelete", redis_client=object())
    analysis.collect_core_conflict = lambda _: core_conflict

    result = analysis.analyse(
        AnalysisInput(
            git_dir="/repos/repo.git",
            git_repo_name="owner/repo.git",
            merge_commit_oid="merge-sha",
        )
    )

    assert result is not None
    _, output = result
    assert isinstance(output, InfoConflictModifyDelete)
    assert output.conflicted_tree_oid == "conflicted-tree"
    assert [conflict.model_dump() for conflict in output.conflicts] == [
        {
            "logical_conflict_index": 0,
            "path": "deleted-by-theirs.txt",
            "base_oid": "base",
            "ours_oid": "ours",
            "theirs_oid": None,
        },
        {
            "logical_conflict_index": 0,
            "path": "deleted-by-ours.txt",
            "base_oid": "base-2",
            "ours_oid": None,
            "theirs_oid": "theirs",
        },
    ]


def test_modifydelete_info_skips_core_records_without_modifydelete_conflicts():
    core_conflict = InfoConflictCore(
        repo="owner/repo.git",
        merge_commit_oid="merge-sha",
        merge_result=MergeResult(result_tree_oid="tree", conflicted_files=[], logical_conflicts=[]),
    )
    analysis = ModifyDeleteInfoAnalysis("modifydelete", redis_client=object())
    analysis.collect_core_conflict = lambda _: core_conflict

    assert analysis.analyse(AnalysisInput(git_dir="/repos", git_repo_name="owner/repo.git", merge_commit_oid="merge-sha")) is None
