from unittest.mock import patch

from playbook.start import Playground, load_playbook


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
