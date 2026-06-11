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


def test_diff_analysis_records_colored_diff(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout="\x1b[31m-diff\x1b[m\n",
            stderr="",
        )

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.diff_to_actual_resolution == "\x1b[31m-diff\x1b[m\n"
    assert record.error is None
    dumped = record.model_dump()
    assert "configuration" not in dumped
    assert "hook_result" not in dumped
    assert "git_archive" not in dumped
    assert diff_capture_git.call_args.args == (
        "-C",
        "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
        "diff",
        "--color=always",
        "HEAD",
        "actualsha",
    )


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
    assert record.diff_to_actual_resolution is None
    assert record.error == "Could not diff proposed resolution against actual resolution: bad diff"


def test_diff_analysis_records_missing_playgrounds(monkeypatch):
    monkeypatch.delenv("PLAYGROUNDS", raising=False)

    record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.diff_to_actual_resolution is None
    assert record.error == "PLAYGROUNDS environment variable is not set"


def test_diff_analysis_records_unreadable_head(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with patch("evaluation.analysis.common.capture_git") as head_capture_git:
        head_capture_git.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="bad head")

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha is None
    assert record.diff_to_actual_resolution is None
    assert record.error == "Could not read resolved HEAD: bad head"


def test_diff_analysis_rejects_playground_name_without_merge_sha(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    record = DiffEvaluationAnalysis().analyse(evaluation_input("owner/repo.git"))

    assert record.diff_to_actual_resolution is None
    assert record.error == "Could not extract merge SHA from playground name: owner/repo.git"
