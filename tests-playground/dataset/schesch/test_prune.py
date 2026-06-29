from dataset.schesch.prune import (
    ConflictKey,
    group_merge_pairs_by_repo,
    group_playgrounds_by_repo,
    intersect_allowed_merge_shas,
    parse_conflict_key,
    prune_conflict_keys,
    repo_cache_path,
    resolve_allowed_merge_shas,
    resolve_allowed_merge_shas_from_playbook,
)
from dataset.schesch.count import ScheschMergePair
from playbook.playgrounds import Playground, PlaybookLoadResult


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


def test_group_merge_pairs_by_repo_normalizes_dataset_repo_to_cache_key():
    grouped = group_merge_pairs_by_repo(
        [
            ScheschMergePair(
                repo="owner/repo",
                left_parent="left",
                right_parent="right",
            )
        ]
    )

    assert grouped == {"owner/repo.git": {("left", "right")}}


def test_group_playgrounds_by_repo_groups_playbook_entries():
    grouped = group_playgrounds_by_repo(
        [
            Playground(repo_name="owner/repo.git", merge_sha="one"),
            Playground(repo_name="owner/repo.git", merge_sha="two"),
            Playground(repo_name="other/repo.git", merge_sha="three"),
        ]
    )

    assert {
        repo: [playground.merge_sha for playground in playgrounds]
        for repo, playgrounds in grouped.items()
    } == {
        "owner/repo.git": ["one", "two"],
        "other/repo.git": ["three"],
    }


def test_repo_cache_path_normalizes_dataset_repo_to_bare_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHES", str(tmp_path / "caches"))

    assert repo_cache_path("owner/repo") == tmp_path / "caches" / "repos" / "owner" / "repo.git"


def test_resolve_allowed_merge_shas_keeps_repo_with_unresolved_parent_pairs(monkeypatch):
    def fake_merge_parent_index(repo):
        assert repo == "owner/repo.git"
        return {frozenset(("left1", "right1")): ["merge1"]}

    monkeypatch.setattr("dataset.schesch.prune.merge_parent_index", fake_merge_parent_index)

    result = resolve_allowed_merge_shas(
        [
            ScheschMergePair(repo="owner/repo", left_parent="left1", right_parent="right1"),
            ScheschMergePair(repo="owner/repo", left_parent="left2", right_parent="right2"),
        ]
    )

    assert result.allowed_by_repo == {"owner/repo.git": {"merge1"}}
    assert result.skipped_repos == set()
    assert result.unresolved_parent_pairs == 1
    assert result.repos_with_unresolved_parent_pairs == 1
    assert result.ambiguous_parent_pairs == 0


def test_resolve_allowed_merge_shas_prunes_ambiguous_parent_pairs(monkeypatch):
    def fake_merge_parent_index(repo):
        assert repo == "owner/repo.git"
        return {frozenset(("left1", "right1")): ["merge1", "merge2"]}

    monkeypatch.setattr("dataset.schesch.prune.merge_parent_index", fake_merge_parent_index)

    result = resolve_allowed_merge_shas(
        [
            ScheschMergePair(repo="owner/repo", left_parent="left1", right_parent="right1"),
        ]
    )

    assert result.allowed_by_repo == {"owner/repo.git": set()}
    assert result.ambiguous_parent_pairs == 1
    assert result.repos_with_ambiguous_parent_pairs == 1


def test_resolve_allowed_merge_shas_from_playbook_uses_playground_resolution(monkeypatch, tmp_path):
    playgrounds = [
        Playground(repo_name="owner/repo.git", merge_sha="merge1"),
        Playground(repo_name="owner/repo.git", parent_shas=("left", "right")),
        Playground(repo_name="other/repo.git", merge_sha="merge3"),
    ]
    monkeypatch.setattr(
        "dataset.schesch.prune.load_playbook_result",
        lambda path: PlaybookLoadResult(playgrounds=playgrounds),
    )
    monkeypatch.setattr(
        "dataset.schesch.prune.resolve_playground_merge_sha",
        lambda playground: "merge2" if playground.parent_shas else playground.merge_sha,
    )

    result = resolve_allowed_merge_shas_from_playbook(tmp_path / "schesch.yaml")

    assert result.allowed_by_repo == {
        "owner/repo.git": {"merge1", "merge2"},
        "other/repo.git": {"merge3"},
    }
    assert result.skipped_repos == set()
    assert result.unresolved_parent_pairs == 0


def test_resolve_allowed_merge_shas_from_playbook_skips_repo_with_unresolved_entry(monkeypatch, tmp_path):
    playgrounds = [
        Playground(repo_name="owner/repo.git", merge_sha="merge1"),
        Playground(repo_name="owner/repo.git", parent_shas=("missing-left", "missing-right")),
        Playground(repo_name="other/repo.git", merge_sha="merge3"),
    ]
    monkeypatch.setattr(
        "dataset.schesch.prune.load_playbook_result",
        lambda path: PlaybookLoadResult(playgrounds=playgrounds),
    )

    def fake_resolve_playground_merge_sha(playground):
        if playground.parent_shas:
            raise RuntimeError("missing parents")
        return playground.merge_sha

    monkeypatch.setattr(
        "dataset.schesch.prune.resolve_playground_merge_sha",
        fake_resolve_playground_merge_sha,
    )

    result = resolve_allowed_merge_shas_from_playbook(tmp_path / "schesch.yaml")

    assert result.allowed_by_repo == {"other/repo.git": {"merge3"}}
    assert result.skipped_repos == {"owner/repo.git"}
    assert result.unresolved_parent_pairs == 1
    assert result.repos_with_unresolved_parent_pairs == 1


def test_intersect_allowed_merge_shas_keeps_only_merge_analysis_and_playbook_overlap():
    assert intersect_allowed_merge_shas(
        {
            "owner/repo.git": {"merge1", "merge2"},
            "merge-analysis-only/repo.git": {"merge3"},
        },
        {
            "owner/repo.git": {"merge2", "merge4"},
            "playbook-only/repo.git": {"merge5"},
        },
    ) == {"owner/repo.git": {"merge2"}}


def test_prune_conflict_keys_deletes_only_dataset_repo_keys_not_in_allowed_set():
    redis = FakeRedis(
        [
            "info:conflict:core:owner/repo.git:keep",
            "info:conflict:octopus:owner/repo.git:delete",
            "info:conflict:core:other/repo.git:unrelated",
        ]
    )

    result = prune_conflict_keys(
        redis,
        {"owner/repo.git": {"keep"}},
        dry_run=False,
    )

    assert redis.deleted == ["info:conflict:octopus:owner/repo.git:delete"]
    assert result.scanned == 2
    assert result.kept == 1
    assert result.deleted == 1
    assert result.skipped == 1


def test_prune_conflict_keys_deletes_all_keys_for_scoped_repo_without_allowed_shas():
    redis = FakeRedis(
        [
            "info:conflict:core:owner/repo.git:delete1",
            "info:conflict:octopus:owner/repo.git:delete2",
            "info:conflict:core:other/repo.git:skip",
        ]
    )

    result = prune_conflict_keys(
        redis,
        {},
        dry_run=False,
        prunable_repos={"owner/repo.git"},
    )

    assert redis.deleted == [
        "info:conflict:core:owner/repo.git:delete1",
        "info:conflict:octopus:owner/repo.git:delete2",
    ]
    assert result.scanned == 2
    assert result.kept == 0
    assert result.deleted == 2
    assert result.skipped == 1


def test_prune_conflict_keys_dry_run_does_not_delete():
    redis = FakeRedis(["info:conflict:core:owner/repo.git:delete"])

    result = prune_conflict_keys(redis, {"owner/repo.git": {"keep"}}, dry_run=True)

    assert redis.deleted == []
    assert result.deleted == 1
