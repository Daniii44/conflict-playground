from datetime import datetime, timezone
from pathlib import Path
import subprocess

from common.merge_tree import MergeLogicalConflict, MergeResult
from dataset.schesch.tests.generate import (
    GeneratedTestFile,
    ScheschGeneratedTests,
    commit_generated_tests,
    content_conflict_paths,
    format_generated_patch,
    generate_tests,
    generated_tests_record_key,
    prompt_for_file,
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


def test_generate_tests_stores_error_record_when_opencode_fails(monkeypatch, tmp_path):
    redis = FakeRedis()
    redis.json_api.values["info:conflict:core:owner/repo.git:merge-sha"] = core_conflict().model_dump()
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "owner" / "repo.git-merge-sha"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(
        "dataset.schesch.tests.generate.setup_playground",
        lambda repo, merge: "owner/repo.git-merge-sha",
    )
    monkeypatch.setattr("dataset.schesch.tests.generate.prepare_human_solution_worktree", lambda path, merge: None)
    monkeypatch.setattr(
        "dataset.schesch.tests.generate.run_opencode_for_file",
        lambda path, executable, prompt, timeout: (1, "bad output", "opencode exited with code 1", 0.5),
    )

    record = generate_tests(redis, "owner/repo.git", "merge-sha")

    assert record.error == "Test generation failed for src/Main.java: opencode exited with code 1"
    assert record.files[0].path == "src/Main.java"
    assert record.files[0].output_tail == "bad output"
    stored = redis.json_api.values["dataset:schesch:tests:owner/repo.git:merge-sha"]
    assert stored["error"] == record.error
    assert stored["coverage"] is None


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
