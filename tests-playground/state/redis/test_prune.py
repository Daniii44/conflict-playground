from fnmatch import fnmatch

import pytest

from state.redis import prune as redis_prune


class FakeRedis:
    def __init__(self, keys=None):
        self.keys = list(keys or [])
        self.deleted = []

    def scan_iter(self, match):
        for key in self.keys:
            text = key.decode("utf-8") if isinstance(key, bytes) else key
            if fnmatch(text, match):
                yield key

    def delete(self, key):
        self.deleted.append(key)
        return 1


def test_collect_exclusive_playbook_identifiers_uses_override_merge_shas(tmp_path, monkeypatch):
    playbook_path = tmp_path / "overrides.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/example/project.git
      override_merge_shas:
        - merge-a
        - parents:
            - left
            - right
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))
    monkeypatch.setattr(
        redis_prune,
        "resolve_playground_merge_sha",
        lambda playground: playground.merge_sha or "resolved-from-parents",
    )

    assert redis_prune.collect_exclusive_playbook_identifiers("overrides") == {
        "example/project.git:merge-a",
        "example/project.git:resolved-from-parents",
    }


def test_collect_exclusive_playbook_identifiers_rejects_non_override_sources(tmp_path, monkeypatch):
    playbook_path = tmp_path / "mixed.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/example/project.git
      limit: 1
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))

    with pytest.raises(ValueError, match="override_merge_shas"):
        redis_prune.collect_exclusive_playbook_identifiers("mixed")


def test_main_prunes_only_keys_not_in_selected_playgrounds(monkeypatch):
    redis = FakeRedis(
        keys=[
            b"info:conflict:core:example/project.git:merge-a",
            b"info:conflict:core:example/project.git:merge-b",
            b"resolution:conflict:example/project.git-merge-a:20260722T120000.000000Z",
        ]
    )
    monkeypatch.setattr(redis_prune, "setup_data_redis_connection", lambda: redis)
    monkeypatch.setattr(
        redis_prune,
        "collect_exclusive_playbook_identifiers",
        lambda playbook: {"example/project.git:merge-a"},
    )
    monkeypatch.setattr(
        redis_prune.sys,
        "argv",
        ["state-redis-prune", "info:conflict:*", "--not-in-playground", "selected"],
    )

    redis_prune.main()

    assert redis.deleted == [b"info:conflict:core:example/project.git:merge-b"]


def test_main_exits_when_not_in_playground_playbook_is_not_override_only(monkeypatch):
    monkeypatch.setattr(
        redis_prune,
        "collect_exclusive_playbook_identifiers",
        lambda playbook: (_ for _ in ()).throw(ValueError("override_merge_shas required")),
    )
    monkeypatch.setattr(
        redis_prune.sys,
        "argv",
        ["state-redis-prune", "info:conflict:*", "--not-in-playground", "mixed"],
    )

    with pytest.raises(SystemExit) as excinfo:
        redis_prune.main()

    assert excinfo.value.code == 1
