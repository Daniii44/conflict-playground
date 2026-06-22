from datetime import datetime
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.sync import (
    analysis_result_exists,
    selected_analysis_names,
    playground_name_from_resolution_key,
    restored_playground_name_from_resolution_key,
    sync_evaluations,
)
from evaluation.analysis.common import evaluation_record_key


def test_resolution_key_parsing_preserves_original_playground_name():
    key = "resolution:conflict:owner/repo-with-hyphen.git-abc123:20260609T120000.000000Z"

    assert playground_name_from_resolution_key(key) == "owner/repo-with-hyphen.git-abc123"


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

    assert selected_analysis_names(Args()) == ["core", "diff", "schesch", "summary"]

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


def test_sync_evaluations_logs_failed_evaluation_as_error():
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

    assert synced == 1
    logger.error.assert_called_once_with(
        "Stored failed evaluation at {}: {}",
        "evaluation:merge:summary:owner/repo.git-abc:20260609T120000.000000Z",
        "hook failed",
    )
