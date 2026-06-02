from dataset.schesch.prune import (
    ConflictKey,
    parse_conflict_key,
    prune_conflict_keys,
)


class FakeRedis:
    def __init__(self, keys):
        self.keys = list(keys)
        self.deleted = []

    def scan_iter(self, match):
        assert match == "info:conflict:*"
        return iter(self.keys)

    def delete(self, key):
        self.deleted.append(key)


def test_parse_conflict_key_extracts_repo_and_merge_sha():
    assert parse_conflict_key("info:conflict:core:owner/repo.git:abc123") == ConflictKey(
        key="info:conflict:core:owner/repo.git:abc123",
        analysis="core",
        repo="owner/repo.git",
        merge_sha="abc123",
    )


def test_parse_conflict_key_rejects_other_keys():
    assert parse_conflict_key("runtime:active_playground:x") is None
    assert parse_conflict_key("info:conflict:core") is None


def test_prune_conflict_keys_deletes_only_dataset_repo_keys_not_in_allowed_set():
    redis = FakeRedis(
        [
            "info:conflict:core:owner/repo.git:keep",
            "info:conflict:tree-diff:owner/repo.git:delete",
            "info:conflict:core:other/repo.git:unrelated",
        ]
    )

    result = prune_conflict_keys(
        redis,
        {"owner/repo.git": {"keep"}},
        dry_run=False,
    )

    assert redis.deleted == ["info:conflict:tree-diff:owner/repo.git:delete"]
    assert result.scanned == 2
    assert result.kept == 1
    assert result.deleted == 1
    assert result.skipped == 1


def test_prune_conflict_keys_dry_run_does_not_delete():
    redis = FakeRedis(["info:conflict:core:owner/repo.git:delete"])

    result = prune_conflict_keys(redis, {"owner/repo.git": {"keep"}}, dry_run=True)

    assert redis.deleted == []
    assert result.deleted == 1
