from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput, ScheschResolutionResult
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.schesch_analysis import ScheschEvaluationAnalysis


def evaluation_input():
    return EvaluationInput(
        resolution_key="resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z",
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
            proposed_resolution=ProposedResolution(git_archive="archive"),
        ),
    )


def successful_git(*args, **kwargs):
    return CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")


def configure_java_homes(monkeypatch, tmp_path):
    for env_var in ("JAVA8_HOME", "JAVA11_HOME", "JAVA17_HOME"):
        java_home = tmp_path / env_var.lower()
        (java_home / "bin").mkdir(parents=True)
        monkeypatch.setenv(env_var, str(java_home))


def test_schesch_analysis_records_compilation_failure(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "pom.xml").write_text("<project />")
    configure_java_homes(monkeypatch, tmp_path)

    with (
        patch("evaluation.analysis.schesch_analysis.capture_git", side_effect=successful_git),
        patch("evaluation.analysis.schesch_analysis.read_head_commit", return_value=("head-sha", None)),
        patch("evaluation.analysis.schesch_analysis.subprocess.run") as run,
    ):
        run.return_value = CompletedProcess(args=[], returncode=1, stdout="compile failed", stderr="")

        record = ScheschEvaluationAnalysis(timeout_seconds=900).run_tests_for_ref(
            repo_path,
            "HEAD",
            "proposed",
            "head-sha",
        )

    assert not record.passed
    assert record.compilation_failed
    assert not record.test_execution_failed
    assert not record.timed_out
    assert len(record.attempts) == 3
    assert all(attempt.test_result is None for attempt in record.attempts)
    assert all(
        attempt.compile_result is not None and attempt.compile_result.duration_seconds >= 0
        for attempt in record.attempts
    )
    assert [call.args[0] for call in run.call_args_list] == [
        ["mvn", "clean", "test-compile"],
        ["mvn", "clean", "test-compile"],
        ["mvn", "clean", "test-compile"],
    ]


def test_schesch_analysis_records_test_execution_failure(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "gradlew").write_text("#!/usr/bin/env bash\n")
    configure_java_homes(monkeypatch, tmp_path)

    with (
        patch("evaluation.analysis.schesch_analysis.capture_git", side_effect=successful_git),
        patch("evaluation.analysis.schesch_analysis.read_head_commit", return_value=("head-sha", None)),
        patch("evaluation.analysis.schesch_analysis.subprocess.run") as run,
    ):
        run.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
        ]

        record = ScheschEvaluationAnalysis(timeout_seconds=900).run_tests_for_ref(
            repo_path,
            "HEAD",
            "proposed",
            "head-sha",
        )

    assert not record.passed
    assert not record.compilation_failed
    assert record.test_execution_failed
    assert not record.timed_out
    assert len(record.attempts) == 3
    assert all(attempt.test_result is not None for attempt in record.attempts)
    assert all(
        attempt.compile_result is not None and attempt.compile_result.duration_seconds >= 0
        for attempt in record.attempts
    )
    assert all(
        attempt.test_result is not None and attempt.test_result.duration_seconds >= 0
        for attempt in record.attempts
    )
    assert [call.args[0] for call in run.call_args_list] == [
        ["./gradlew", "clean", "testClasses"],
        ["./gradlew", "clean", "test"],
        ["./gradlew", "clean", "testClasses"],
        ["./gradlew", "clean", "test"],
        ["./gradlew", "clean", "testClasses"],
        ["./gradlew", "clean", "test"],
    ]


def test_schesch_analysis_runs_proposed_then_human_resolution(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    analysis = ScheschEvaluationAnalysis(timeout_seconds=900)

    with (
        patch("evaluation.analysis.schesch_analysis.read_head_commit", return_value=("proposed-sha", None)),
        patch.object(analysis, "run_tests_for_ref") as run_tests,
        patch.object(analysis, "prepare_worktree", return_value=None) as prepare_worktree,
    ):
        run_tests.side_effect = [
            ScheschResolutionResult(label="proposed", commit_sha="proposed-sha", passed=True),
            ScheschResolutionResult(label="human", commit_sha="actualsha", passed=True),
        ]

        record = analysis.analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.proposed is not None
    assert record.proposed.passed
    assert record.human is not None
    assert record.human.passed
    assert [call.args for call in run_tests.call_args_list] == [
        (Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"), "HEAD", "proposed", "proposed-sha"),
        (
            Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"),
            "actualsha",
            "human",
            "actualsha",
        ),
    ]
    prepare_worktree.assert_called_once_with(
        Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"),
        "proposed-sha",
    )
