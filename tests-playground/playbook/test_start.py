from unittest.mock import patch

from playbook.start import Playground, load_playbook, merge_parent_index, resolve_merge_sha_from_parents


def test_load_playbook_applies_config_conflict_types_to_sources(tmp_path):
    playbook_path = tmp_path / "source-config.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-types:
      - CONFLICT (contents)
  sources:
    - repo_url: https://github.com/example/project.git
      limit: 2
""",
        encoding="utf-8",
    )

    with patch("playbook.start.list_conflicts", return_value=[("example/project.git", "abc123")]) as list_conflicts:
        playgrounds = load_playbook(str(playbook_path))

    list_conflicts.assert_called_once_with(
        repos=["example/project.git"],
        conflict_types=["CONFLICT (contents)"],
        limit=2,
    )
    assert playgrounds == [Playground(repo_name="example/project.git", merge_sha="abc123")]


def test_load_playbook_uses_empty_conflict_types_when_source_config_missing(tmp_path):
    playbook_path = tmp_path / "source-no-config.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/example/project.git
""",
        encoding="utf-8",
    )

    with patch("playbook.start.list_conflicts", return_value=[("example/project.git", "abc123")]) as list_conflicts:
        playgrounds = load_playbook(str(playbook_path))

    list_conflicts.assert_called_once_with(
        repos=["example/project.git"],
        conflict_types=[],
        limit=1,
    )
    assert playgrounds == [Playground(repo_name="example/project.git", merge_sha="abc123")]


def test_load_playbook_applies_config_conflict_types_without_sources(tmp_path):
    playbook_path = tmp_path / "dynamic.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-types:
      - CONFLICT (rename/delete)
  sources:
""",
        encoding="utf-8",
    )

    with patch("playbook.start.list_conflicts", return_value=[("example/project.git", "def456")]) as list_conflicts:
        playgrounds = load_playbook(str(playbook_path))

    list_conflicts.assert_called_once_with(conflict_types=["CONFLICT (rename/delete)"])
    assert playgrounds == [Playground(repo_name="example/project.git", merge_sha="def456")]


def test_load_playbook_does_not_query_conflicts_for_override_shas(tmp_path):
    playbook_path = tmp_path / "override.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-types:
      - CONFLICT (contents)
  sources:
    - repo_url: https://github.com/example/project.git
      override_merge_shas:
        - abc123
        - def456
""",
        encoding="utf-8",
    )

    with patch("playbook.start.list_conflicts") as list_conflicts:
        playgrounds = load_playbook(str(playbook_path))

    list_conflicts.assert_not_called()
    assert playgrounds == [
        Playground(repo_name="example/project.git", merge_sha="abc123"),
        Playground(repo_name="example/project.git", merge_sha="def456"),
    ]


def test_load_playbook_accepts_parent_pair_overrides(tmp_path):
    playbook_path = tmp_path / "override-parents.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/example/project.git
      override_merge_shas:
        - parents:
            - left123
            - right456
        - merge_sha: abc123
""",
        encoding="utf-8",
    )

    with patch("playbook.start.list_conflicts") as list_conflicts:
        playgrounds = load_playbook(str(playbook_path))

    list_conflicts.assert_not_called()
    assert playgrounds == [
        Playground(repo_name="example/project.git", parent_shas=("left123", "right456")),
        Playground(repo_name="example/project.git", merge_sha="abc123"),
    ]


def test_resolve_merge_sha_from_parents_matches_parent_pair(monkeypatch, tmp_path):
    merge_parent_index.cache_clear()
    caches = tmp_path / "caches"
    bare_repo = caches / "repos" / "example" / "project.git"
    bare_repo.mkdir(parents=True)
    monkeypatch.setenv("CACHES", str(caches))

    class Result:
        stdout = (
            "merge1 other parent\n"
            "merge2 left123 right456\n"
            "merge3 right456 left123\n"
        )

    with patch("playbook.start.capture_git", return_value=Result()):
        merge_sha = resolve_merge_sha_from_parents(
            "example/project.git",
            ("left123", "right456"),
        )

    assert merge_sha == "merge2"
