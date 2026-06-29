from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from dataset.schesch.tests.generate import ScheschGeneratedTests


def load_generate_missing_module():
    repo_root = Path(__file__).resolve().parents[4]
    source_root = repo_root / "src-playground"
    if not source_root.is_dir():
        source_root = repo_root / "src"
    module_path = source_root / "dataset" / "schesch" / "tests" / "generate-missing.py"
    spec = importlib.util.spec_from_file_location("generate_missing", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_has_usable_generated_tests_requires_successful_patch():
    module = load_generate_missing_module()

    assert not module.has_usable_generated_tests(FakeRedis(), "missing")
    assert not module.has_usable_generated_tests(FakeRedis({"key": generated_record(error="failed")}), "key")
    assert not module.has_usable_generated_tests(FakeRedis({"key": generated_record(patch="")}), "key")
    assert module.has_usable_generated_tests(FakeRedis({"key": generated_record()}), "key")


def test_selected_playgrounds_applies_skip_and_limit(monkeypatch, tmp_path):
    module = load_generate_missing_module()
    playgrounds = [
        module.Playground(repo_name="owner/repo.git", merge_sha="one"),
        module.Playground(repo_name="owner/repo.git", merge_sha="two"),
        module.Playground(repo_name="owner/repo.git", merge_sha="three"),
    ]
    monkeypatch.setattr(module, "load_playbook_result", lambda path: SimpleNamespace(playgrounds=playgrounds))

    selected = module.selected_playgrounds(tmp_path / "playbook.yaml", skip=1, limit=1)

    assert [playground.merge_sha for playground in selected] == ["two"]


def test_generate_missing_tests_skips_existing_and_generates_missing(monkeypatch, tmp_path):
    module = load_generate_missing_module()
    existing_key = "dataset:schesch:tests:owner/repo.git:existing"
    redis = FakeRedis({existing_key: generated_record(merge_sha="existing", redis_key=existing_key)})
    playgrounds = [
        module.Playground(repo_name="owner/repo.git", merge_sha="existing"),
        module.Playground(repo_name="owner/repo.git", merge_sha="missing"),
    ]
    generated = []

    monkeypatch.setattr(module, "load_playbook_result", lambda path: SimpleNamespace(playgrounds=playgrounds))
    monkeypatch.setattr(module, "resolve_playground_merge_sha", lambda playground: playground.merge_sha)

    def fake_generate_tests(redis_arg, repo_name, merge_sha, **kwargs):
        generated.append((repo_name, merge_sha, kwargs))
        return ScheschGeneratedTests(
            repo=repo_name,
            merge_sha=merge_sha,
            redis_key=f"dataset:schesch:tests:{repo_name}:{merge_sha}",
            conflict_info_key=f"info:conflict:core:{repo_name}:{merge_sha}",
            human_solution_ref=merge_sha,
            generated_at=datetime.now(timezone.utc),
            duration_seconds=1.0,
            patch="patch",
        )

    monkeypatch.setattr(module, "generate_tests", fake_generate_tests)

    result = module.generate_missing_tests_for_playbook(redis, tmp_path / "playbook.yaml", timeout_seconds=3)

    assert result.total == 2
    assert result.skipped == 1
    assert result.generated == 1
    assert result.failed == 0
    assert generated == [
        (
            "owner/repo.git",
            "missing",
            {
                "opencode_executable": module.DEFAULT_OPENCODE_EXECUTABLE,
                "timeout_seconds": 3,
                "keep_playground": False,
            },
        )
    ]


def test_generate_missing_tests_records_failures_and_continues(monkeypatch, tmp_path):
    module = load_generate_missing_module()
    redis = FakeRedis()
    playgrounds = [
        module.Playground(repo_name="owner/repo.git", merge_sha="failed"),
        module.Playground(repo_name="owner/repo.git", merge_sha="next"),
    ]

    monkeypatch.setattr(module, "load_playbook_result", lambda path: SimpleNamespace(playgrounds=playgrounds))
    monkeypatch.setattr(module, "resolve_playground_merge_sha", lambda playground: playground.merge_sha)

    def fake_generate_tests(redis_arg, repo_name, merge_sha, **kwargs):
        return ScheschGeneratedTests(
            repo=repo_name,
            merge_sha=merge_sha,
            redis_key=f"dataset:schesch:tests:{repo_name}:{merge_sha}",
            conflict_info_key=f"info:conflict:core:{repo_name}:{merge_sha}",
            human_solution_ref=merge_sha,
            generated_at=datetime.now(timezone.utc),
            duration_seconds=1.0,
            error="generation failed" if merge_sha == "failed" else None,
            patch=None if merge_sha == "failed" else "patch",
        )

    monkeypatch.setattr(module, "generate_tests", fake_generate_tests)

    result = module.generate_missing_tests_for_playbook(redis, tmp_path / "playbook.yaml")

    assert result.total == 2
    assert result.generated == 1
    assert result.failed == 1
    assert result.failed_keys == ["dataset:schesch:tests:owner/repo.git:failed"]


def test_main_uses_default_schesch_playbook(monkeypatch, tmp_path, capsys):
    module = load_generate_missing_module()
    playbook_path = tmp_path / "schesch.yaml"
    playbook_path.write_text("playbook:\n  sources: []\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(module, "default_playbook_output_path", lambda: playbook_path)
    monkeypatch.setattr(module, "setup_redis_connection", lambda: "redis")
    monkeypatch.setattr(module.sys, "argv", ["dataset-schesch-tests-generate-missing", "--limit", "1"])

    def fake_generate_missing_tests_for_playbook(redis, path, **kwargs):
        calls.append((redis, path, kwargs))
        return module.MissingGenerationResult(total=1, generated=1)

    monkeypatch.setattr(module, "generate_missing_tests_for_playbook", fake_generate_missing_tests_for_playbook)

    assert module.main() == 0
    assert calls == [
        (
            "redis",
            playbook_path,
            {
                "opencode_executable": module.DEFAULT_OPENCODE_EXECUTABLE,
                "timeout_seconds": module.DEFAULT_OPENCODE_TIMEOUT_SECONDS,
                "keep_playground": False,
                "skip": 0,
                "limit": 1,
                "stop_on_error": False,
            },
        )
    ]
    assert "total=1 generated=1 skipped=0 failed=0" in capsys.readouterr().out


def test_main_rejects_missing_default_schesch_playbook(monkeypatch, tmp_path):
    module = load_generate_missing_module()

    monkeypatch.setattr(module, "default_playbook_output_path", lambda: tmp_path / "missing.yaml")
    monkeypatch.setattr(module.sys, "argv", ["dataset-schesch-tests-generate-missing"])

    assert module.main() == 1


def test_parse_args_rejects_positional_playbook(monkeypatch):
    module = load_generate_missing_module()

    monkeypatch.setattr(module.sys, "argv", ["dataset-schesch-tests-generate-missing", "other"])

    with pytest.raises(SystemExit):
        module.parse_args()
