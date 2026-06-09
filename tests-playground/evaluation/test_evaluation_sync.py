from evaluation.sync import (
    playground_name_from_resolution_key,
    restored_playground_name_from_resolution_key,
)


def test_resolution_key_parsing_preserves_original_playground_name():
    key = "resolution:conflict:owner/repo-with-hyphen.git-abc123:20260609T120000.000000Z"

    assert playground_name_from_resolution_key(key) == "owner/repo-with-hyphen.git-abc123"


def test_restored_playground_name_includes_timestamp_before_merge_sha():
    key = "resolution:conflict:owner/repo-with-hyphen.git-abc123:20260609T120000.000000Z"

    restored_name = restored_playground_name_from_resolution_key(key)

    assert restored_name == "owner/repo-with-hyphen.git-20260609T120000.000000Z-abc123"
    assert restored_name.rsplit("-", 1)[1] == "abc123"
