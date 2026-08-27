from datetime import datetime
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import (
    MergeEvaluationRecord,
    MergeScheschEvaluation,
    ScheschCommandResult,
    ScheschJavaAttempt,
    ScheschResolutionResult,
)
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.sync import (
    analysis_result_exists,
    evaluate_resolution,
    iter_resolution_keys,
    restored_playground_name_from_resolution_key,
    selected_analysis_names,
    sync_evaluations,
)
from evaluation.analysis.common import evaluation_record_key


def test_restored_playground_name_includes_timestamp_before_merge_sha():
    key = "resolution:conflict:owner/repo-with-hyphen.git-abc123:20260609T120000.000000Z"

    restored_name = restored_playground_name_from_resolution_key(key)

    assert restored_name == "owner/repo-with-hyphen.git-20260609T120000.000000Z-abc123"
    assert restored_name.rsplit("-", 1)[1] == "abc123"


def test_resolution_key_maps_to_deterministic_evaluation_keys():
    key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"

    assert evaluation_record_key("core", key) == (
        "evaluation:merge:core:owner/repo.git-abc:20260609T120000.000000Z"
    )
    assert evaluation_record_key("diff", key) == (
        "evaluation:merge:diff:owner/repo.git-abc:20260609T120000.000000Z"
    )
    assert evaluation_record_key("sem", key) == (
        "evaluation:merge:sem:owner/repo.git-abc:20260609T120000.000000Z"
    )


class FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)

    def exists(self, key):
        return key in self.keys


def test_analysis_result_exists_checks_deterministic_key():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"
    redis = FakeRedis([
        "evaluation:merge:core:owner/repo.git-abc:20260609T120000.000000Z",
    ])

    assert analysis_result_exists(redis, "core", resolution_key)
    assert not analysis_result_exists(redis, "diff", resolution_key)


def test_all_analysis_includes_summary():
    class Args:
        all_analysis = True
        analysis = None

    assert selected_analysis_names(Args()) == [
        "core",
        "diff",
        "sem",
        "classification",
        "schesch-original",
        "schesch-generated",
        "summary",
        "modifydelete",
        "rename",
    ]


class FakeRedisJson:
    def __init__(self, values=None):
        self.values = values or {}
        self.set_calls = []

    def get(self, key):
        return self.values.get(key)

    def set(self, *args):
        self.set_calls.append(args)


class SyncFakeRedis(FakeRedis):
    def __init__(self, keys, values=None):
        super().__init__(keys)
        self.json_api = FakeRedisJson(values)

    def scan_iter(self, match):
        prefix = match.removesuffix("*")
        return (key for key in self.keys if key.startswith(prefix))

    def json(self):
        return self.json_api


def test_iter_resolution_keys_scans_all_resolution_records():
    redis = SyncFakeRedis(
        [
            "resolution:conflict:owner/repo.git-def:20260609T130000.000000Z",
            "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z",
            "evaluation:merge:core:owner/repo.git-abc:20260609T120000.000000Z",
        ]
    )

    assert iter_resolution_keys(redis) == [
        "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z",
        "resolution:conflict:owner/repo.git-def:20260609T130000.000000Z",
    ]


def test_sync_evaluations_skips_unsuccessful_resolution():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"
    resolution = ConflictResolution(
        configuration=Configuration(
            hook_type="opencode",
            playground_version="test",
            volume_type="bind-mount",
            resolution_start=datetime(2026, 6, 9, 12, 0, 0),
        ),
        resolution_end=datetime(2026, 6, 9, 12, 1, 0),
        proposed_resolution=ProposedResolution(error="hook failed"),
    ).model_dump(mode="json")
    redis = SyncFakeRedis([resolution_key], {resolution_key: resolution})

    with (
        patch("evaluation.sync.setup_redis_connection", return_value=redis),
        patch("evaluation.sync.logger") as logger,
    ):
        synced = sync_evaluations(analyses=["summary"])

    assert synced == 0
    assert redis.json_api.set_calls == []
    logger.info.assert_any_call("Skipping unsuccessful resolution {}", resolution_key)
    logger.error.assert_not_called()


def test_sync_upgrades_existing_schesch_failure_with_two_test_only_retries(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"
    evaluation_key = evaluation_record_key("schesch-original", resolution_key)
    existing = MergeScheschEvaluation(
        resolution_key=resolution_key,
        proposed_commit_sha="proposed-sha",
        actual_resolution_sha="abc",
        timeout_seconds=900,
        proposed=ScheschResolutionResult(
            label="proposed",
            commit_sha="proposed-sha",
            test_execution_failed=True,
            attempts=[
                ScheschJavaAttempt(
                    java_home="/java-17",
                    compile_result=ScheschCommandResult(
                        command=["mvn", "clean", "test-compile"],
                        returncode=0,
                        duration_seconds=1.0,
                    ),
                    test_result=ScheschCommandResult(
                        command=["mvn", "clean", "test"],
                        returncode=1,
                        duration_seconds=1.0,
                    ),
                )
            ],
        ),
    )
    redis = SyncFakeRedis(
        [resolution_key, evaluation_key],
        {
            resolution_key: archived_resolution().model_dump(mode="json"),
            evaluation_key: existing.model_dump(mode="json"),
        },
    )

    with (
        patch("evaluation.sync.setup_redis_connection", return_value=redis),
        patch("evaluation.sync.restore_resolution") as restore_resolution,
        patch("evaluation.sync.remove_restored_playground", return_value=None) as remove_restored_playground,
        patch("evaluation.analysis.schesch_original_analysis.reset_playground", return_value=None) as reset_playground,
        patch("common.schesch.ScheschResolutionRunner.run_command") as run_command,
    ):
        run_command.side_effect = [
            ScheschCommandResult(command=["mvn", "clean", "test"], returncode=1, duration_seconds=1.0),
            ScheschCommandResult(command=["mvn", "clean", "test"], returncode=0, duration_seconds=1.0),
        ]

        synced = sync_evaluations(analyses=["schesch-original"])

    assert synced == 1
    restore_resolution.assert_called_once_with("owner/repo.git-20260609T120000.000000Z-abc", "archive")
    remove_restored_playground.assert_called_once_with("owner/repo.git-20260609T120000.000000Z-abc")
    assert reset_playground.call_count == 2
    assert [call.args[1] for call in run_command.call_args_list] == [
        ["mvn", "clean", "test"],
        ["mvn", "clean", "test"],
    ]
    assert len(redis.json_api.set_calls) == 1
    stored = redis.json_api.set_calls[0][2]
    assert stored["test_execution_retries"] == 2
    assert stored["proposed"]["passed"] is True
    assert stored["proposed"]["test_execution_failed"] is False
    assert [result["returncode"] for result in stored["proposed"]["attempts"][0]["test_results"]] == [1, 1, 0]


def test_sync_marks_existing_schesch_compilation_failure_without_restoring_or_retrying():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"
    evaluation_key = evaluation_record_key("schesch-original", resolution_key)
    existing = MergeScheschEvaluation(
        resolution_key=resolution_key,
        proposed_commit_sha="proposed-sha",
        actual_resolution_sha="abc",
        timeout_seconds=900,
        proposed=ScheschResolutionResult(
            label="proposed",
            commit_sha="proposed-sha",
            compilation_failed=True,
        ),
    )
    redis = SyncFakeRedis(
        [resolution_key, evaluation_key],
        {
            resolution_key: archived_resolution().model_dump(mode="json"),
            evaluation_key: existing.model_dump(mode="json"),
        },
    )

    with (
        patch("evaluation.sync.setup_redis_connection", return_value=redis),
        patch("evaluation.sync.restore_resolution") as restore_resolution,
        patch("common.schesch.ScheschResolutionRunner.run_command") as run_command,
    ):
        synced = sync_evaluations(analyses=["schesch-original"])

    assert synced == 1
    restore_resolution.assert_not_called()
    run_command.assert_not_called()
    assert redis.json_api.set_calls[0][2]["test_execution_retries"] == 2


def test_sync_skips_existing_schesch_record_already_updated_for_test_retries():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"
    evaluation_key = evaluation_record_key("schesch-original", resolution_key)
    existing = MergeScheschEvaluation(
        resolution_key=resolution_key,
        timeout_seconds=900,
        test_execution_retries=2,
        proposed=ScheschResolutionResult(label="proposed", test_execution_failed=True),
    )
    redis = SyncFakeRedis(
        [resolution_key, evaluation_key],
        {
            resolution_key: archived_resolution().model_dump(mode="json"),
            evaluation_key: existing.model_dump(mode="json"),
        },
    )

    with (
        patch("evaluation.sync.setup_redis_connection", return_value=redis),
        patch("evaluation.sync.restore_resolution") as restore_resolution,
    ):
        synced = sync_evaluations(analyses=["schesch-original"])

    assert synced == 0
    restore_resolution.assert_not_called()
    assert redis.json_api.set_calls == []


class FakeAnalysis:
    def __init__(self, name="fake", error=None):
        self.name = name
        self.error = error

    def get_analysis_name(self):
        return self.name

    def analyse(self, evaluation_input):
        if self.error is not None:
            raise self.error
        return MergeEvaluationRecord(resolution_key=evaluation_input.resolution_key)


def archived_resolution():
    return ConflictResolution(
        configuration=Configuration(
            hook_type="opencode",
            playground_version="test",
            volume_type="bind-mount",
            resolution_start=datetime(2026, 6, 9, 12, 0, 0),
        ),
        resolution_end=datetime(2026, 6, 9, 12, 1, 0),
        proposed_resolution=ProposedResolution(git_archive="archive"),
    )


def test_evaluate_resolution_removes_restored_playground_after_analysis():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"

    with (
        patch("evaluation.sync.restore_resolution") as restore_resolution,
        patch("evaluation.sync.remove_restored_playground", return_value=None) as remove_restored_playground,
    ):
        results = evaluate_resolution(resolution_key, archived_resolution(), [FakeAnalysis()])

    assert len(results) == 1
    restore_resolution.assert_called_once_with("owner/repo.git-20260609T120000.000000Z-abc", "archive")
    remove_restored_playground.assert_called_once_with("owner/repo.git-20260609T120000.000000Z-abc")


def test_evaluate_resolution_removes_restored_playground_after_analysis_error():
    resolution_key = "resolution:conflict:owner/repo.git-abc:20260609T120000.000000Z"

    with (
        patch("evaluation.sync.restore_resolution"),
        patch("evaluation.sync.remove_restored_playground", return_value=None) as remove_restored_playground,
    ):
        try:
            evaluate_resolution(resolution_key, archived_resolution(), [FakeAnalysis(error=RuntimeError("boom"))])
        except RuntimeError as error:
            assert str(error) == "boom"
        else:
            raise AssertionError("Expected analysis error")

    remove_restored_playground.assert_called_once_with("owner/repo.git-20260609T120000.000000Z-abc")
