from subprocess import CompletedProcess
from unittest.mock import patch

from common.evaluation_models import ScheschResolutionResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.schesch_analysis import InfoConflictSchesch, ScheschInfoAnalysis


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        git_dir="/repos/example.git",
        git_repo_name="owner/repo.git",
        merge_commit_oid="merge-sha",
    )


def test_schesch_info_analysis_runs_human_and_parent_refs(monkeypatch, tmp_path):
    analysis = ScheschInfoAnalysis(timeout_seconds=900)
    worktree_path = tmp_path / "owner" / "repo.git-merge-sha"
    run_calls = []
    monkeypatch.setenv("PLAYGROUNDS", str(tmp_path))

    with (
        patch.object(analysis, "collect_parents", return_value=["left-sha", "right-sha"]),
        patch("info.conflict.analysis.schesch_analysis.setup_playground") as setup_playground,
        patch.object(analysis, "run_tests_for_ref") as run_tests,
        patch("info.conflict.analysis.schesch_analysis.shutil.rmtree") as rmtree,
    ):
        run_tests.side_effect = lambda path, ref, label, commit_sha: run_calls.append(
            (path, ref, label, commit_sha)
        ) or ScheschResolutionResult(label=label, commit_sha=commit_sha, passed=True)
        result = analysis.analyse(analysis_input())

    assert result is not None
    returned_input, conflict = result
    assert returned_input == analysis_input()
    assert isinstance(conflict, InfoConflictSchesch)
    assert conflict.repo == "owner/repo.git"
    assert conflict.merge_commit_oid == "merge-sha"
    assert conflict.actual_resolution_sha == "merge-sha"
    assert conflict.parent_shas == ["left-sha", "right-sha"]
    assert conflict.human is not None
    assert conflict.human.label == "human"
    assert [parent.label for parent in conflict.parents] == ["parent-1", "parent-2"]
    assert run_calls == [
        (worktree_path, "merge-sha", "human", "merge-sha"),
        (worktree_path, "left-sha", "parent-1", "left-sha"),
        (worktree_path, "right-sha", "parent-2", "right-sha"),
    ]
    setup_playground.assert_called_once_with("owner/repo.git", "merge-sha")
    rmtree.assert_called_once_with(worktree_path, ignore_errors=True)


def test_schesch_info_analysis_records_parent_count_error():
    analysis = ScheschInfoAnalysis(timeout_seconds=900)

    with patch.object(analysis, "collect_parents", return_value=["only-parent"]):
        result = analysis.analyse(analysis_input())

    assert result is not None
    _, conflict = result
    assert isinstance(conflict, InfoConflictSchesch)
    assert conflict.error == "Expected exactly 2 parents, found 1"
    assert conflict.parent_shas == ["only-parent"]
    assert conflict.human is None
    assert conflict.parents == []


def test_schesch_info_analysis_collects_parents():
    analysis = ScheschInfoAnalysis()

    with patch("info.conflict.analysis.schesch_analysis.capture_git") as capture_git:
        capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="left right\n", stderr="")

        assert analysis.collect_parents(analysis_input()) == ["left", "right"]

    capture_git.assert_called_once_with(
        "--git-dir=/repos/example.git",
        "show",
        "--no-patch",
        "--format=%P",
        "merge-sha",
        check=False,
    )


def test_schesch_info_analysis_enables_stream_output():
    assert ScheschInfoAnalysis(stream_output=True).stream_output
