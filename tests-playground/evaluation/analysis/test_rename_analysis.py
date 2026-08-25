from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.rename_analysis import RenameEvaluationAnalysis


def evaluation_input():
    return EvaluationInput(
        resolution_key="resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z",
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha",
        resolution=ConflictResolution(
            configuration=Configuration(hook_type="manual-cli", playground_version="test", volume_type="bind-mount", resolution_start=datetime(2026, 6, 2, 12, 0, 0)),
            resolution_end=datetime(2026, 6, 2, 12, 0, 5),
            proposed_resolution=ProposedResolution(git_archive="archive"),
        ),
    )


def merge_result():
    return MergeResult(
        result_tree_oid="conflicted-tree",
        conflicted_files=[],
        logical_conflicts=[
            MergeLogicalConflict(type=ConflictType.CONFLICT_DIR_RENAME_SUGGESTED, info="rename", paths=["suggested.txt"]),
            MergeLogicalConflict(type=ConflictType.CONFLICT_RENAME_DELETE, info="rename", paths=["deleted.txt"]),
            MergeLogicalConflict(type=ConflictType.CONFLICT_RENAME_RENAME, info="rename", paths=["left.txt", "right.txt"]),
            MergeLogicalConflict(type=ConflictType.CONFLICT_DIR_RENAME_SPLIT, info="rename", paths=["split.txt"]),
            MergeLogicalConflict(type=ConflictType.CONFLICT_CONTENTS, info="content", paths=["ignored.txt"]),
        ],
    )


def test_rename_evaluation_compares_only_path_presence(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    analysis = RenameEvaluationAnalysis()
    presences = {
        ("HEAD", "suggested.txt"): True,
        ("actualsha", "suggested.txt"): False,
        ("HEAD", "deleted.txt"): False,
        ("actualsha", "deleted.txt"): False,
        ("HEAD", "left.txt"): True,
        ("actualsha", "left.txt"): True,
        ("HEAD", "right.txt"): False,
        ("actualsha", "right.txt"): True,
        ("HEAD", "split.txt"): True,
        ("actualsha", "split.txt"): False,
    }

    with (
        patch("evaluation.analysis.rename_analysis.read_head_commit", return_value=("proposed-sha", None)),
        patch.object(analysis, "collect_parents", return_value=(["left", "right"], None)),
        patch.object(analysis, "collect_merge_result", return_value=(merge_result(), None)),
        patch.object(analysis, "path_exists", side_effect=lambda _path, ref, path: (presences[(ref, path)], None)),
    ):
        record = analysis.analyse(evaluation_input())

    assert record.error is None
    assert record.conflicted_tree_oid == "conflicted-tree"
    assert [item.path for item in record.path_evaluations] == ["suggested.txt", "deleted.txt", "left.txt", "right.txt", "split.txt"]
    assert [item.contradiction for item in record.path_evaluations] == [True, False, False, True, True]
    assert all(item.path != "ignored.txt" for item in record.path_evaluations)


def test_path_exists_uses_ls_tree_without_reading_file_contents():
    analysis = RenameEvaluationAnalysis()
    with patch("evaluation.analysis.rename_analysis.capture_git") as capture_git:
        capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="file.txt\0", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]

        assert analysis.path_exists("/playground", "HEAD", "file.txt") == (True, None)
        assert analysis.path_exists("/playground", "HEAD", "missing.txt") == (False, None)

    assert [call.args for call in capture_git.call_args_list] == [
        ("-C", "/playground", "ls-tree", "--name-only", "-z", "HEAD", "--", "file.txt"),
        ("-C", "/playground", "ls-tree", "--name-only", "-z", "HEAD", "--", "missing.txt"),
    ]
