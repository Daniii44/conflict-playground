from datetime import datetime, timezone
import subprocess

import pytest

from dataset.schesch.tests.apply import (
    apply_patch_to_current_head,
    load_generated_tests,
    resolve_record_key,
)
from dataset.schesch.tests.generate import ScheschGeneratedTests


class FakeJson:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values=None):
        self.json_api = FakeJson(values)

    def json(self):
        return self.json_api


def generated_record(**overrides):
    record = ScheschGeneratedTests(
        repo="owner/repo.git",
        merge_sha="merge-sha",
        redis_key="dataset:schesch:tests:owner/repo.git:merge-sha",
        conflict_info_key="info:conflict:core:owner/repo.git:merge-sha",
        human_solution_ref="merge-sha",
        generated_at=datetime.now(timezone.utc),
        duration_seconds=1.0,
        patch="From abc Mon Sep 17 00:00:00 2001\npatch\n",
    )
    return record.model_dump() | overrides


def completed(args, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def test_load_generated_tests_requires_existing_patch():
    redis = FakeRedis({"key": generated_record(patch=None)})

    with pytest.raises(RuntimeError, match="has no patch"):
        load_generated_tests(redis, "key")


def test_load_generated_tests_rejects_error_record():
    redis = FakeRedis({"key": generated_record(error="generation failed")})

    with pytest.raises(RuntimeError, match="generation failed"):
        load_generated_tests(redis, "key")


def test_resolve_record_key_from_repo_and_merge():
    class Args:
        key = None
        repo_name = "owner/repo.git"
        merge_sha = "merge-sha"
        parents = None

    assert resolve_record_key(Args) == "dataset:schesch:tests:owner/repo.git:merge-sha"


def test_apply_patch_refuses_dirty_worktree(monkeypatch, tmp_path):
    def fake_capture_git(*args, **kwargs):
        if args[-2:] == ("rev-parse", "--is-inside-work-tree"):
            return completed(args, stdout="true\n")
        if args[-2:] == ("status", "--porcelain"):
            return completed(args, stdout=" M existing.txt\n")
        raise AssertionError(args)

    monkeypatch.setattr("dataset.schesch.tests.apply.capture_git", fake_capture_git)

    with pytest.raises(RuntimeError, match="worktree is not clean"):
        apply_patch_to_current_head(tmp_path, "patch")


def test_apply_patch_runs_git_am_and_returns_new_head(monkeypatch, tmp_path):
    calls = []

    def fake_capture_git(*args, **kwargs):
        calls.append(args)
        if args[-2:] == ("rev-parse", "--is-inside-work-tree"):
            return completed(args, stdout="true\n")
        if args[-2:] == ("status", "--porcelain"):
            return completed(args)
        if args[-2:] == ("rev-parse", "HEAD"):
            return completed(args, stdout="new-head\n" if calls.count(args) > 1 else "old-head\n")
        if args[-2:] == ("ls-files", "-u"):
            return completed(args)
        raise AssertionError(args)

    def fake_run(args, **kwargs):
        assert args == ["git", "am", "--3way"]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["input"] == "patch"
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        return completed(args)

    monkeypatch.setattr("dataset.schesch.tests.apply.capture_git", fake_capture_git)
    monkeypatch.setattr("dataset.schesch.tests.apply.subprocess.run", fake_run)

    assert apply_patch_to_current_head(tmp_path, "patch") == "new-head"


def test_apply_patch_aborts_failed_git_am(monkeypatch, tmp_path):
    abort_calls = []

    def fake_capture_git(*args, **kwargs):
        if args[-2:] == ("rev-parse", "--is-inside-work-tree"):
            return completed(args, stdout="true\n")
        if args[-2:] == ("status", "--porcelain"):
            return completed(args)
        if args[-2:] == ("rev-parse", "HEAD"):
            return completed(args, stdout="old-head\n")
        if args[-2:] == ("am", "--abort"):
            abort_calls.append(args)
            return completed(args)
        raise AssertionError(args)

    monkeypatch.setattr("dataset.schesch.tests.apply.capture_git", fake_capture_git)
    monkeypatch.setattr(
        "dataset.schesch.tests.apply.subprocess.run",
        lambda *args, **kwargs: completed(args, stderr="patch failed", returncode=1),
    )

    with pytest.raises(RuntimeError, match="failed and was aborted"):
        apply_patch_to_current_head(tmp_path, "patch")

    assert abort_calls == [("-C", str(tmp_path), "am", "--abort")]
