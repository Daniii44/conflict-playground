from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.core_analysis import CoreEvaluationAnalysis


def evaluation_input(proposed_resolution=None):
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    return EvaluationInput(
        resolution_key=resolution_key,
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha",
        resolution=ConflictResolution(
            configuration=Configuration(
                hook_type="manual-cli",
                playground_version="test",
                volume_type="bind-mount",
                resolution_start=datetime(2026, 6, 2, 12, 0, 0),
            ),
            resolution_end=datetime(2026, 6, 2, 12, 0, 5),
            proposed_resolution=proposed_resolution,
        ),
    )


def archived_resolution():
    return ProposedResolution(commit_sha="saved-sha", actual_resolution_sha="actualsha", git_archive="archive")


def test_core_analysis_records_success(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.core_analysis.capture_git") as core_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        core_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="actualsha parent-a parent-b\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]

        record = CoreEvaluationAnalysis().analyse(evaluation_input(archived_resolution()))

    assert record.resolution_key == "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    assert record.duration_seconds == 5.0
    assert not record.incomplete_merge
    assert record.perfect_match
    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.error is None
    dumped = record.model_dump()
    assert "configuration" not in dumped
    assert "hook_result" not in dumped
    assert "git_archive" not in dumped
    assert "diff_to_actual_resolution" not in dumped
    assert [call.args for call in core_capture_git.call_args_list] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "rev-list",
            "--parents",
            "-n",
            "1",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "merge-base",
            "--is-ancestor",
            "parent-a",
            "HEAD",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "merge-base",
            "--is-ancestor",
            "parent-b",
            "HEAD",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff",
            "--quiet",
            "actualsha",
            "HEAD",
        ),
    ]


def test_core_analysis_records_incomplete_merge(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.core_analysis.capture_git") as core_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        core_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="actualsha parent-a parent-b\n", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        ]

        record = CoreEvaluationAnalysis().analyse(evaluation_input(archived_resolution()))

    assert record.incomplete_merge
    assert not record.perfect_match


def test_core_analysis_records_imperfect_diff(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.core_analysis.capture_git") as core_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        core_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="actualsha parent-a parent-b\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        ]

        record = CoreEvaluationAnalysis().analyse(evaluation_input(archived_resolution()))

    assert not record.incomplete_merge
    assert not record.perfect_match


def test_core_analysis_records_missing_archive_error():
    record = CoreEvaluationAnalysis().analyse(
        evaluation_input(ProposedResolution(error="hook failed", git_archive=None))
    )

    assert record.incomplete_merge
    assert not record.perfect_match
    assert record.error == "hook failed"


def test_core_analysis_records_missing_proposed_resolution_error():
    record = CoreEvaluationAnalysis().analyse(evaluation_input(None))

    assert record.incomplete_merge
    assert not record.perfect_match
    assert record.error == "Resolution has no proposed_resolution"
