from datetime import datetime, timezone
import importlib.util
from pathlib import Path

from common.evaluation_models import ScheschResolutionResult
from dataset.schesch.tests.generate import ScheschGeneratedTests, encode_patch_base64


def load_backfill_human_module():
    repo_root = Path(__file__).resolve().parents[4]
    source_root = repo_root / "src-playground"
    if not source_root.is_dir():
        source_root = repo_root / "src"
    module_path = source_root / "dataset" / "schesch" / "tests" / "backfill-human.py"
    spec = importlib.util.spec_from_file_location("backfill_human", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeJson:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, path, value):
        self.values[key] = value


class FakeRedis:
    def __init__(self, values=None):
        self.json_api = FakeJson(values)

    def json(self):
        return self.json_api

    def scan_iter(self, match):
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.json_api.values):
            if key.startswith(prefix):
                yield key


def generated_record(**overrides):
    merge_sha = overrides.get("merge_sha", "merge-sha")
    record = ScheschGeneratedTests(
        repo="owner/repo.git",
        merge_sha=merge_sha,
        redis_key=overrides.get("redis_key", f"dataset:schesch:tests:owner/repo.git:{merge_sha}"),
        conflict_info_key=overrides.get("conflict_info_key", f"info:conflict:core:owner/repo.git:{merge_sha}"),
        human_solution_ref=overrides.get("human_solution_ref", merge_sha),
        generated_at=datetime.now(timezone.utc),
        duration_seconds=1.0,
        patch_base64=encode_patch_base64(
            (
                "From abc Mon Sep 17 00:00:00 2001\n"
                "diff --git a/src/test/java/pkg/OneTest.java b/src/test/java/pkg/OneTest.java\n"
                "+++ b/src/test/java/pkg/OneTest.java\n"
            ).encode()
        ),
    )
    return record.model_dump(mode="json") | overrides


def test_generated_test_keys_returns_sorted_matching_keys():
    module = load_backfill_human_module()
    redis = FakeRedis(
        {
            "dataset:schesch:tests:owner/repo.git:b": generated_record(merge_sha="b"),
            "dataset:schesch:tests:owner/repo.git:a": generated_record(merge_sha="a"),
            "other:key": {},
        }
    )

    assert module.generated_test_keys(redis) == [
        "dataset:schesch:tests:owner/repo.git:a",
        "dataset:schesch:tests:owner/repo.git:b",
    ]


def test_backfill_missing_human_records_updates_only_missing_human(monkeypatch):
    module = load_backfill_human_module()
    missing_key = "dataset:schesch:tests:owner/repo.git:missing"
    existing_key = "dataset:schesch:tests:owner/repo.git:existing"
    redis = FakeRedis(
        {
            missing_key: generated_record(merge_sha="missing", redis_key=missing_key, human=None),
            existing_key: generated_record(
                merge_sha="existing",
                redis_key=existing_key,
                human={"label": "human", "passed": True},
            ),
        }
    )
    monkeypatch.setattr(
        module,
        "backfill_human_result",
        lambda redis_arg, record, **kwargs: ScheschResolutionResult(
            label="human",
            commit_sha=record.human_solution_ref,
            passed=True,
            successful_java_home="/java-17",
        ),
    )

    result = module.backfill_missing_human_records(redis)

    assert result.total == 2
    assert result.updated == 1
    assert result.skipped == 1
    assert result.failed == 0
    assert redis.json_api.values[missing_key]["error"] is None
    assert redis.json_api.values[missing_key]["human"] == {
        "label": "human",
        "commit_sha": "missing",
        "build_tool": None,
        "passed": True,
        "compilation_failed": False,
        "test_execution_failed": False,
        "timed_out": False,
        "successful_java_home": "/java-17",
        "error": None,
        "attempts": [],
    }


def test_backfill_human_result_returns_error_result_for_missing_patch():
    module = load_backfill_human_module()
    redis = FakeRedis()
    record = ScheschGeneratedTests(
        repo="owner/repo.git",
        merge_sha="merge-sha",
        redis_key="dataset:schesch:tests:owner/repo.git:merge-sha",
        conflict_info_key="info:conflict:core:owner/repo.git:merge-sha",
        human_solution_ref="merge-sha",
        generated_at=datetime.now(timezone.utc),
        duration_seconds=1.0,
    )

    result = module.backfill_human_result(redis, record)

    assert result.label == "human"
    assert result.commit_sha == "merge-sha"
    assert result.error == "Generated test suite has no patch"


def test_backfill_missing_human_records_sets_top_level_error_from_failed_human_result(monkeypatch):
    module = load_backfill_human_module()
    key = "dataset:schesch:tests:owner/repo.git:failed-human"
    redis = FakeRedis({key: generated_record(merge_sha="failed-human", redis_key=key, human=None)})
    monkeypatch.setattr(
        module,
        "backfill_human_result",
        lambda redis_arg, record, **kwargs: ScheschResolutionResult(
            label="human",
            commit_sha=record.human_solution_ref,
            test_execution_failed=True,
        ),
    )

    result = module.backfill_missing_human_records(redis)

    assert result.updated == 1
    assert redis.json_api.values[key]["error"] == "Human sample resolution fails Schesch tests under the expected Java home"


def test_backfill_missing_human_records_skips_existing_error_without_running_tests(monkeypatch):
    module = load_backfill_human_module()
    key = "dataset:schesch:tests:owner/repo.git:error"
    redis = FakeRedis({key: generated_record(merge_sha="error", redis_key=key, human=None, error="existing error")})
    called = {"backfill": False}

    def fake_backfill(*args, **kwargs):
        called["backfill"] = True
        raise AssertionError("backfill_human_result should not be called")

    monkeypatch.setattr(module, "backfill_human_result", fake_backfill)

    result = module.backfill_missing_human_records(redis)

    assert result.updated == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert not called["backfill"]
    assert redis.json_api.values[key]["human"] is None
    assert redis.json_api.values[key]["error"] == "existing error"


def test_main_uses_requested_limit(monkeypatch, capsys):
    module = load_backfill_human_module()
    calls = []
    monkeypatch.setattr(module, "setup_redis_connection", lambda: "redis")
    monkeypatch.setattr(
        module,
        "backfill_missing_human_records",
        lambda redis, **kwargs: (
            calls.append((redis, kwargs))
            or module.BackfillHumanResult(total=1, updated=1)
        ),
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["dataset-schesch-tests-backfill-human", "--limit", "1"],
    )

    assert module.main() == 0
    assert calls == [
        (
            "redis",
            {
                "timeout_seconds": module.DEFAULT_OPENCODE_TIMEOUT_SECONDS,
                "keep_playground": False,
                "limit": 1,
                "stop_on_error": False,
            },
        )
    ]
    assert "total=1 updated=1 skipped=0 failed=0" in capsys.readouterr().out
