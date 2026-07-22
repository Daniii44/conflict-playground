from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput, ScheschResolutionResult
from common.schesch import (
    ScheschResolutionRunner,
    determine_expected_java_home,
    filtered_test_command,
    BuildCommands,
    normalize_test_selector,
    parse_schesch_playground_name,
    reset_playground,
)
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
        patch("common.schesch.capture_git", side_effect=successful_git),
        patch("common.schesch.read_head_commit", return_value=("head-sha", None)),
        patch("common.schesch.subprocess.run") as run,
    ):
        run.return_value = CompletedProcess(args=[], returncode=1, stdout="compile failed", stderr="")

        record = ScheschResolutionRunner(timeout_seconds=900).run_tests_for_ref(
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
        patch("common.schesch.capture_git", side_effect=successful_git),
        patch("common.schesch.read_head_commit", return_value=("head-sha", None)),
        patch("common.schesch.subprocess.run") as run,
    ):
        run.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="compiled", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="tests failed", stderr=""),
        ]

        record = ScheschResolutionRunner(timeout_seconds=900).run_tests_for_ref(
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


def test_schesch_runner_streams_command_output_when_enabled(monkeypatch, tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    java_home = tmp_path / "java"
    (java_home / "bin").mkdir(parents=True)

    with patch("common.schesch.subprocess.run") as run:
        run.return_value = CompletedProcess(args=[], returncode=0, stdout=None, stderr=None)

        record = ScheschResolutionRunner(stream_output=True).run_command(
            repo_path,
            ["mvn", "test"],
            str(java_home),
            deadline=10**12,
        )

    assert record.returncode == 0
    assert record.output_tail == ""
    assert run.call_args.args[0] == ["mvn", "test"]
    assert "capture_output" not in run.call_args.kwargs


def test_reset_playground_resets_in_place_to_target_ref(tmp_path):
    repo_path = tmp_path / "repo"
    calls = []

    def fake_capture_git(*args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch("common.schesch.capture_git", side_effect=fake_capture_git):
        assert reset_playground(repo_path, "target-sha") is None

    assert calls == [
        (("-C", str(repo_path), "reset", "--hard"), {"check": False}),
        (("-C", str(repo_path), "clean", "-fdx"), {"check": False}),
        (("-C", str(repo_path), "checkout", "--detach", "--force", "target-sha"), {"check": False}),
        (("-C", str(repo_path), "reset", "--hard", "target-sha"), {"check": False}),
        (("-C", str(repo_path), "clean", "-fdx"), {"check": False}),
    ]


def test_parse_schesch_playground_name_supports_setup_and_restored_names():
    assert parse_schesch_playground_name("owner/repo-with-hyphen.git-merge-sha") == (
        "owner/repo-with-hyphen.git",
        "merge-sha",
    )
    assert parse_schesch_playground_name("owner/repo-with-hyphen.git-20260602T120000.000000Z-merge-sha") == (
        "owner/repo-with-hyphen.git",
        "merge-sha",
    )


def test_determine_expected_java_home_requires_one_passing_environment():
    java_home, error = determine_expected_java_home(
        {
            "human": {"passed": True, "successful_java_home": "/java-17", "build_tool": "maven"},
            "parents": [
                {"passed": True, "successful_java_home": "/java-17", "build_tool": "maven"},
                {"passed": True, "successful_java_home": "/java-17", "build_tool": "maven"},
            ],
        }
    )
    assert java_home == "/java-17"
    assert error is None

    java_home, error = determine_expected_java_home(
        {
            "human": {"passed": True, "successful_java_home": "/java-17"},
            "parents": [
                {"passed": True, "successful_java_home": "/java-17"},
                {"passed": True, "successful_java_home": "/java-11"},
            ],
        }
    )
    assert java_home is None
    assert error == "Schesch info record does not resolve to one successful Java home"


def test_normalize_test_selector_strips_path_and_java_suffix():
    assert normalize_test_selector("D4mDbQueryAccumuloInterfaceTest.java") == "D4mDbQueryAccumuloInterfaceTest"
    assert normalize_test_selector("src/test/java/pkg/D4mDbQueryAccumuloInterfaceTest.java") == (
        "D4mDbQueryAccumuloInterfaceTest"
    )
    assert normalize_test_selector("pkg\\D4mDbQueryAccumuloInterfaceTest.java") == "D4mDbQueryAccumuloInterfaceTest"
    assert normalize_test_selector("AlreadyNormalizedTest") == "AlreadyNormalizedTest"


def test_filtered_test_command_supports_gradle_and_maven():
    gradle = BuildCommands("gradle", ["./gradlew", "clean", "testClasses"], ["./gradlew", "clean", "test"])
    maven = BuildCommands("maven", ["mvn", "clean", "test-compile"], ["mvn", "clean", "test"])

    assert filtered_test_command(gradle, ["OneTest.java", "pkg/TwoTest.java"]) == [
        "./gradlew",
        "clean",
        "test",
        "--tests",
        "OneTest",
        "--tests",
        "TwoTest",
    ]
    assert filtered_test_command(maven, ["OneTest.java", "pkg/TwoTest.java"]) == [
        "mvn",
        "clean",
        "test",
        "-Dtest=OneTest,TwoTest",
    ]


def test_schesch_analysis_runs_proposed_resolution_only(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    analysis = ScheschEvaluationAnalysis(timeout_seconds=900)

    with (
        patch("evaluation.analysis.schesch_analysis.read_head_commit", return_value=("proposed-sha", None)),
        patch.object(analysis, "run_tests_for_ref") as run_tests,
        patch("evaluation.analysis.schesch_analysis.reset_playground", return_value=None) as reset_playground,
    ):
        run_tests.side_effect = [
            ScheschResolutionResult(label="proposed", commit_sha="proposed-sha", passed=True),
        ]

        record = analysis.analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.proposed is not None
    assert record.proposed.passed
    assert [call.args for call in run_tests.call_args_list] == [
        (Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"), "HEAD", "proposed", "proposed-sha"),
    ]
    reset_playground.assert_called_once_with(
        Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"),
        "proposed-sha",
    )
