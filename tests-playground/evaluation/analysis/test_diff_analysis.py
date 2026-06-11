from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.diff_analysis import DiffEvaluationAnalysis


def evaluation_input(restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha"):
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    return EvaluationInput(
        resolution_key=resolution_key,
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name=restored_playground_name,
        resolution=ConflictResolution(
            configuration=Configuration(
                hook_type="manual-cli",
                playground_version="test",
                volume_type="bind-mount",
                resolution_start=datetime(2026, 6, 2, 12, 0, 0),
            ),
            resolution_end=datetime(2026, 6, 2, 12, 0, 5),
            proposed_resolution=ProposedResolution(git_archive="archive"),
        ),
    )


def test_diff_analysis_records_patch_and_raw_diff_tree_outputs(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="patch to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="raw to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="p1 p2\n", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="conflicted-tree\0metadata", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="patch conflicted to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="raw conflicted to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="patch from conflicted\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="raw from conflicted\n", stderr=""),
        ]

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.conflicted_tree_oid == "conflicted-tree"
    assert record.proposed_to_actual_resolution_patch == "patch to actual\n"
    assert record.proposed_to_actual_resolution_raw == "raw to actual\n"
    assert record.conflicted_to_actual_resolution_patch == "patch conflicted to actual\n"
    assert record.conflicted_to_actual_resolution_raw == "raw conflicted to actual\n"
    assert record.conflicted_to_proposed_resolution_patch == "patch from conflicted\n"
    assert record.conflicted_to_proposed_resolution_raw == "raw from conflicted\n"
    assert record.error is None
    dumped = record.model_dump()
    assert "configuration" not in dumped
    assert "hook_result" not in dumped
    assert "git_archive" not in dumped
    assert [call.args for call in diff_capture_git.call_args_list] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "-p",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "show",
            "--no-patch",
            "--format=%P",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "merge-tree",
            "-z",
            "p1",
            "p2",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "-p",
            "conflicted-tree",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "conflicted-tree",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "-p",
            "conflicted-tree",
            "HEAD",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "conflicted-tree",
            "HEAD",
        ),
    ]


def test_diff_analysis_records_diff_command_failure(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="bad diff")

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.proposed_to_actual_resolution_patch is None
    assert record.proposed_to_actual_resolution_raw is None
    assert record.error == "Could not diff proposed resolution against actual resolution: bad diff"


def test_diff_analysis_records_conflicted_tree_comparison_failure_with_reference_diffs(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="patch to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="raw to actual\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="p1 p2\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="clean-tree\0", stderr=""),
        ]

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.proposed_to_actual_resolution_patch == "patch to actual\n"
    assert record.proposed_to_actual_resolution_raw == "raw to actual\n"
    assert record.conflicted_tree_oid is None
    assert record.error == "Actual resolution parents merge cleanly"


def test_diff_analysis_records_missing_playgrounds(monkeypatch):
    monkeypatch.delenv("PLAYGROUNDS", raising=False)

    record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "PLAYGROUNDS environment variable is not set"


def test_diff_analysis_records_unreadable_head(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with patch("evaluation.analysis.common.capture_git") as head_capture_git:
        head_capture_git.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="bad head")

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha is None
    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "Could not read resolved HEAD: bad head"


def test_diff_analysis_rejects_playground_name_without_merge_sha(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    record = DiffEvaluationAnalysis().analyse(evaluation_input("owner/repo.git"))

    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "Could not extract merge SHA from playground name: owner/repo.git"
