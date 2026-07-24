from datetime import datetime, timezone
from pathlib import Path
import subprocess

from common.merge_tree import MergeLogicalConflict, MergeResult
from common.evaluation_models import ScheschResolutionResult
from dataset.schesch.tests.generate import (
    GeneratedTestFile,
    ScheschGeneratedTests,
    commit_generated_tests,
    content_conflict_paths,
    expected_human_java_home,
    format_generated_patch,
    generate_tests,
    generated_test_command,
    generated_tests_record_key,
    human_resolution_error,
    prompt_for_file,
    validate_generated_patch,
    verify_human_solution,
)
from info.conflict.analysis.core_analysis import InfoConflictCore


class FakeJson:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, path, value):
        self.values[key] = value


class FakeRedis:
    def __init__(self):
        self.json_api = FakeJson()

    def json(self):
        return self.json_api


def core_conflict() -> InfoConflictCore:
    return InfoConflictCore(
        repo="owner/repo.git",
        merge_commit_oid="merge-sha",
        merge_result=MergeResult(
            result_tree_oid="tree",
            conflicted_files=[],
            logical_conflicts=[
                MergeLogicalConflict(
                    type="CONFLICT (contents)",
                    info="Merge conflict in src/Main.java",
                    paths=["src/Main.java"],
                ),
                MergeLogicalConflict(
                    type="CONFLICT (contents)",
                    info="Duplicate logical record",
                    paths=["src/Main.java"],
                ),
                MergeLogicalConflict(
                    type="CONFLICT (modify/delete)",
                    info="Not a content conflict",
                    paths=["src/Other.java"],
                ),
            ],
        ),
    )


def test_tests_record_key_uses_requested_prefix():
    assert (
        generated_tests_record_key("owner/repo.git", "abc123")
        == "dataset:schesch:tests:owner/repo.git:abc123"
    )


def test_content_conflict_paths_returns_unique_content_paths_only():
    assert content_conflict_paths(core_conflict()) == ["src/Main.java"]


def test_prompt_for_file_scopes_generation_to_single_conflicting_file():
    prompt = prompt_for_file(core_conflict(), "src/Main.java")

    assert "Generate unit tests" in prompt
    assert "src/Main.java" in prompt
    assert "human sample solution" in prompt
    assert "Do not edit production source files" in prompt
    assert "playground-schesch-test" in prompt
    assert "-t <GeneratedTestClass.java>" in prompt
    assert "Do not run a broader test suite" in prompt
    assert "CONFLICT (contents)" in prompt
    assert "CONFLICT (modify/delete)" not in prompt


def test_commit_generated_tests_returns_none_for_clean_worktree(monkeypatch, tmp_path):
    calls = []

    def fake_capture_git(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("dataset.schesch.tests.generate.capture_git", fake_capture_git)

    assert commit_generated_tests(tmp_path) is None
    assert calls == [("-C", str(tmp_path), "status", "--porcelain")]


def test_format_generated_patch_returns_none_for_empty_patch(monkeypatch, tmp_path):
    def fake_capture_git(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="\n", stderr="")

    monkeypatch.setattr("dataset.schesch.tests.generate.capture_git", fake_capture_git)

    assert format_generated_patch(tmp_path, "base") is None


def test_validate_generated_patch_requires_java_test_changes():
    selectors, error = validate_generated_patch(
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
    )

    assert selectors == []
    assert error == "opencode completed but did not modify any Java test classes"


def test_validate_generated_patch_extracts_changed_test_selectors():
    selectors, error = validate_generated_patch(
        "diff --git a/src/test/java/pkg/OneTest.java b/src/test/java/pkg/OneTest.java\n"
        "--- a/src/test/java/pkg/OneTest.java\n"
        "+++ b/src/test/java/pkg/OneTest.java\n"
    )

    assert selectors == ["OneTest"]
    assert error is None


def test_generate_tests_stores_error_record_when_opencode_fails(monkeypatch, tmp_path):
    redis = FakeRedis()
    redis.json_api.values["info:conflict:core:owner/repo.git:merge-sha"] = core_conflict().model_dump()
    redis.json_api.values["info:conflict:schesch:owner/repo.git:merge-sha"] = {
        "human": {"passed": True, "successful_java_home": "/java-17"},
        "parents": [
            {"passed": True, "successful_java_home": "/java-17"},
            {"passed": True, "successful_java_home": "/java-17"},
        ],
    }
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "owner" / "repo.git-merge-sha"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.setup_playground",
        lambda repo, merge: "owner/repo.git-merge-sha",
    )
    monkeypatch.setattr("dataset.schesch.tests.generate.reset_playground", lambda path, merge: None)
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.run_opencode_for_file",
        lambda path, executable, prompt, timeout: (1, "bad output", "opencode exited with code 1", 0.5),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.ScheschResolutionRunner",
        lambda timeout_seconds: type(
            "Runner",
            (),
            {
                "run_tests_in_current_state": lambda self, path, label, commit_sha=None, java_homes=None: (
                    ScheschResolutionResult(
                        label=label,
                        commit_sha=commit_sha,
                        passed=True,
                        successful_java_home="/java-17",
                    )
                )
            },
        )(),
    )

    record = generate_tests(redis, "owner/repo.git", "merge-sha")

    assert record.error == "Test generation failed for src/Main.java: opencode exited with code 1"
    assert record.human is None
    assert record.files[0].path == "src/Main.java"
    assert record.files[0].output_tail == "bad output"
    stored = redis.json_api.values["dataset:schesch:tests:owner/repo.git:merge-sha"]
    assert stored["error"] == record.error
    assert stored["coverage"] is None


def test_generate_tests_rejects_patch_without_java_test_changes(monkeypatch, tmp_path):
    redis = FakeRedis()
    redis.json_api.values["info:conflict:core:owner/repo.git:merge-sha"] = core_conflict().model_dump()
    redis.json_api.values["info:conflict:schesch:owner/repo.git:merge-sha"] = {
        "human": {"passed": True, "successful_java_home": "/java-17"},
        "parents": [
            {"passed": True, "successful_java_home": "/java-17"},
            {"passed": True, "successful_java_home": "/java-17"},
        ],
    }
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "owner" / "repo.git-merge-sha"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.setup_playground",
        lambda repo, merge: "owner/repo.git-merge-sha",
    )
    monkeypatch.setattr("dataset.schesch.tests.generate.reset_playground", lambda path, merge: None)
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.run_opencode_for_file",
        lambda path, executable, prompt, timeout: (0, None, None, 0.5),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.commit_generated_tests",
        lambda path: "generated-commit",
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.ScheschResolutionRunner",
        lambda timeout_seconds: type(
            "Runner",
            (),
            {
                "run_tests_in_current_state": lambda self, path, label, commit_sha=None, java_homes=None: (
                    ScheschResolutionResult(
                        label=label,
                        commit_sha=commit_sha,
                        passed=True,
                        successful_java_home="/java-17",
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.format_generated_patch",
        lambda path, base_ref: (
            "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
            "--- a/src/main/java/App.java\n"
            "+++ b/src/main/java/App.java\n"
        ),
    )

    record = generate_tests(redis, "owner/repo.git", "merge-sha")

    assert record.test_commit_sha == "generated-commit"
    assert record.error == "opencode completed but did not modify any Java test classes"


def test_expected_human_java_home_uses_schesch_record():
    redis = FakeRedis()
    redis.json_api.values["info:conflict:schesch:owner/repo.git:merge-sha"] = {
        "human": {"passed": True, "successful_java_home": "/java-17"},
        "parents": [
            {"passed": True, "successful_java_home": "/java-17"},
            {"passed": True, "successful_java_home": "/java-17"},
        ],
    }

    assert expected_human_java_home(redis, "owner/repo.git", "merge-sha") == "/java-17"


def test_generated_test_command_uses_filtered_schesch_selectors(monkeypatch, tmp_path):
    captured = {}

    def fake_detect_build_commands(self, playground_path):
        captured["playground_path"] = playground_path
        return type(
            "BuildCommands",
            (),
            {
                "build_tool": "maven",
                "test_command": ["mvn", "clean", "test"],
            },
        )()

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.ScheschResolutionRunner.detect_build_commands",
        fake_detect_build_commands,
    )

    command, build_tool = generated_test_command(tmp_path, ["OneTest", "TwoTest"], 30)

    assert captured["playground_path"] == tmp_path
    assert build_tool == "maven"
    assert command == ["mvn", "clean", "test", "-Dtest=OneTest,TwoTest"]


def test_human_resolution_error_prefers_structured_failure_modes():
    assert human_resolution_error(ScheschResolutionResult(label="human", compilation_failed=True)) == (
        "Human sample resolution does not compile under the expected Java home"
    )
    assert human_resolution_error(ScheschResolutionResult(label="human", test_execution_failed=True)) == (
        "Human sample resolution fails Schesch tests under the expected Java home"
    )
    assert human_resolution_error(ScheschResolutionResult(label="human", timed_out=True)) == (
        "Human sample resolution timed out under the expected Java home"
    )


def test_verify_human_solution_rejects_non_passing_reference(monkeypatch, tmp_path):
    redis = FakeRedis()
    redis.json_api.values["info:conflict:schesch:owner/repo.git:merge-sha"] = {
        "human": {"passed": True, "successful_java_home": "/java-17"},
        "parents": [
            {"passed": True, "successful_java_home": "/java-17"},
            {"passed": True, "successful_java_home": "/java-17"},
        ],
    }

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.generated_test_command",
        lambda playground_path, selectors, timeout_seconds: (["mvn", "clean", "test", "-Dtest=OneTest"], "maven"),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.ScheschResolutionRunner.run_tests_in_current_state",
        lambda self, path, label, commit_sha=None, java_homes=None, test_command=None: (
            ScheschResolutionResult(
                label=label,
                commit_sha=commit_sha,
                test_execution_failed=True,
            )
        ),
    )

    try:
        verify_human_solution(redis, tmp_path, "owner/repo.git", "merge-sha", ["OneTest"], 30)
    except RuntimeError as error:
        assert str(error) == "Human sample resolution fails Schesch tests under the expected Java home"
    else:
        raise AssertionError("Expected human reference failure")


def test_generate_tests_runs_only_generated_selectors_on_human_sample(monkeypatch, tmp_path):
    redis = FakeRedis()
    redis.json_api.values["info:conflict:core:owner/repo.git:merge-sha"] = core_conflict().model_dump()
    redis.json_api.values["info:conflict:schesch:owner/repo.git:merge-sha"] = {
        "human": {"passed": True, "successful_java_home": "/java-17"},
        "parents": [
            {"passed": True, "successful_java_home": "/java-17"},
            {"passed": True, "successful_java_home": "/java-17"},
        ],
    }
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "owner" / "repo.git-merge-sha"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.setup_playground",
        lambda repo, merge: "owner/repo.git-merge-sha",
    )
    monkeypatch.setattr("dataset.schesch.tests.generate.reset_playground", lambda path, merge: None)
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.run_opencode_for_file",
        lambda path, executable, prompt, timeout: (0, None, None, 0.5),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.commit_generated_tests",
        lambda path: "generated-commit",
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.format_generated_patch",
        lambda path, base_ref: (
            "diff --git a/src/test/java/pkg/GeneratedTest.java b/src/test/java/pkg/GeneratedTest.java\n"
            "--- a/src/test/java/pkg/GeneratedTest.java\n"
            "+++ b/src/test/java/pkg/GeneratedTest.java\n"
        ),
    )

    captured = {}
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.generated_test_command",
        lambda playground_path, selectors, timeout_seconds: (
            captured.update(
                {
                    "playground_path": playground_path,
                    "selectors": selectors,
                    "timeout_seconds": timeout_seconds,
                }
            )
            or (["mvn", "clean", "test", "-Dtest=GeneratedTest"], "maven")
        ),
    )
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.ScheschResolutionRunner.run_tests_in_current_state",
        lambda self, path, label, commit_sha=None, java_homes=None, test_command=None: (
            captured.update(
                {
                    "run_path": path,
                    "run_label": label,
                    "run_commit_sha": commit_sha,
                    "run_java_homes": java_homes,
                    "run_test_command": test_command,
                }
            )
            or ScheschResolutionResult(
                label=label,
                commit_sha=commit_sha,
                passed=True,
                successful_java_home="/java-17",
                build_tool="maven",
            )
        ),
    )

    record = generate_tests(redis, "owner/repo.git", "merge-sha", timeout_seconds=45)

    assert record.error is None
    assert record.human is not None
    assert captured == {
        "playground_path": playground,
        "selectors": ["GeneratedTest"],
        "timeout_seconds": 45,
        "run_path": playground,
        "run_label": "human",
        "run_commit_sha": "merge-sha",
        "run_java_homes": ["/java-17"],
        "run_test_command": ["mvn", "clean", "test", "-Dtest=GeneratedTest"],
    }


def test_store_model_keeps_future_coverage_slot():
    record = ScheschGeneratedTests(
        repo="owner/repo.git",
        merge_sha="merge-sha",
        redis_key="dataset:schesch:tests:owner/repo.git:merge-sha",
        conflict_info_key="info:conflict:core:owner/repo.git:merge-sha",
        playground_name="owner/repo.git-merge-sha",
        human_solution_ref="merge-sha",
        generated_at=datetime.now(timezone.utc),
        duration_seconds=1.0,
        files=[GeneratedTestFile(path="src/Main.java", prompt="prompt", duration_seconds=1.0)],
        patch="patch",
    )

    assert record.coverage is None
