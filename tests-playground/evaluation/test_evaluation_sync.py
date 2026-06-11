from evaluation.sync import (
    analysis_result_exists,
    playground_name_from_resolution_key,
    restored_playground_name_from_resolution_key,
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
