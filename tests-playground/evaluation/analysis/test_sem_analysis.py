import json
from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.sem_analysis import SemEvaluationAnalysis


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


def test_sem_analysis_records_json_output(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    sem_payload = {
        "summary": {"fileCount": 1, "added": 0, "modified": 1, "deleted": 0},
        "changes": [{"entityId": "file::chunk::lines 1-1", "changeType": "modified"}],
        "binaryChanges": [],
    }

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.sem_analysis.subprocess.run") as sem_run,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        sem_run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(sem_payload),
            stderr="",
        )

        record = SemEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.proposed_to_actual_sem_diff == sem_payload
    assert record.error is None
    sem_run.assert_called_once()
    assert sem_run.call_args.args == (
        [
            "sem",
            "diff",
            "--no-cosmetics",
            "--json",
            "HEAD",
            "actualsha",
        ],
    )
    assert sem_run.call_args.kwargs["text"] is True
    assert sem_run.call_args.kwargs["capture_output"] is True
    assert sem_run.call_args.kwargs["check"] is False
    assert sem_run.call_args.kwargs["cwd"] == "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"
    assert sem_run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert sem_run.call_args.kwargs["env"]["GIT_ASKPASS"] == "false"


def test_sem_analysis_records_sem_command_failure(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.sem_analysis.subprocess.run") as sem_run,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        sem_run.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="bad sem")

        record = SemEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.proposed_to_actual_sem_diff is None
    assert record.error == "Could not compare proposed resolution against actual resolution: bad sem"


def test_sem_analysis_records_invalid_json(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.sem_analysis.subprocess.run") as sem_run,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        sem_run.return_value = CompletedProcess(args=[], returncode=0, stdout="{not-json", stderr="")

        record = SemEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.proposed_to_actual_sem_diff is None
    assert record.error.startswith(
        "Could not compare proposed resolution against actual resolution: sem returned invalid JSON:"
    )
