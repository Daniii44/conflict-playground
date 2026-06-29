import json
import subprocess
from datetime import datetime
from unittest.mock import patch

import pytest

from common.active_playground_models import ActivePlayground, Configuration
from common.resolution_models import ProposedResolution
from info.conflict.list import ConflictRecord
from playbook import playgrounds as playgrounds_module
from playbook.start import (
    Playground,
    collect_proposed_resolution,
    format_playground_summary_line,
    load_playbook,
    process_playground,
    save_resolution,
    validate_playground_setup,
)


class FakeRedisJson:
    def __init__(self):
        self.set_calls = []
        self.values = {}

    def set(self, *args):
        self.set_calls.append(args)
        key, _, value = args
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self):
        self.json_api = FakeRedisJson()
        self.deleted = []

    def json(self):
        return self.json_api

    def delete(self, key):
        self.deleted.append(key)


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

    with patch(
        "playbook.playgrounds.list_conflict_records",
        return_value=[
            ConflictRecord("example/project.git", "abc123", ("CONFLICT (contents)",)),
        ],
    ) as list_conflict_records:
        playgrounds = load_playbook(str(playbook_path))

    list_conflict_records.assert_called_once_with(
        repos=["example/project.git"],
        conflict_types=["CONFLICT (contents)"],
        limit=2,
    )
    assert playgrounds == [
        Playground(
            repo_name="example/project.git",
            merge_sha="abc123",
            conflict_types=("CONFLICT (contents)",),
        )
    ]


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

    with patch(
        "playbook.playgrounds.list_conflict_records",
        return_value=[
            ConflictRecord("example/project.git", "abc123", ("CONFLICT (contents)",)),
        ],
    ) as list_conflict_records:
        playgrounds = load_playbook(str(playbook_path))

    list_conflict_records.assert_called_once_with(
        repos=["example/project.git"],
        conflict_types=[],
        limit=1,
    )
    assert playgrounds == [
        Playground(
            repo_name="example/project.git",
            merge_sha="abc123",
            conflict_types=("CONFLICT (contents)",),
        )
    ]


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

    with patch(
        "playbook.playgrounds.list_conflict_records",
        return_value=[
            ConflictRecord("example/project.git", "def456", ("CONFLICT (rename/delete)",)),
        ],
    ) as list_conflict_records:
        playgrounds = load_playbook(str(playbook_path))

    list_conflict_records.assert_called_once_with(conflict_types=["CONFLICT (rename/delete)"])
    assert playgrounds == [
        Playground(
            repo_name="example/project.git",
            merge_sha="def456",
            conflict_types=("CONFLICT (rename/delete)",),
        )
    ]


def test_load_playbook_uses_target_percentages_across_sources(tmp_path):
    playbook_path = tmp_path / "source-targets.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-type-percentages:
      CONFLICT (contents): 50
      CONFLICT (rename/rename): 50
  sources:
    - repo_url: https://github.com/example/content-only.git
      limit: 2
    - repo_url: https://github.com/example/mixed.git
      limit: 2
""",
        encoding="utf-8",
    )

    def fake_list_conflict_records(repos, conflict_types):
        assert conflict_types == ["CONFLICT (contents)", "CONFLICT (rename/rename)"]
        if repos == ["example/content-only.git"]:
            return [
                ConflictRecord("example/content-only.git", "content1", ("CONFLICT (contents)",)),
                ConflictRecord("example/content-only.git", "content2", ("CONFLICT (contents)",)),
            ]
        if repos == ["example/mixed.git"]:
            return [
                ConflictRecord("example/mixed.git", "content3", ("CONFLICT (contents)",)),
                ConflictRecord("example/mixed.git", "rename1", ("CONFLICT (rename/rename)",)),
                ConflictRecord("example/mixed.git", "rename2", ("CONFLICT (rename/rename)",)),
            ]
        raise AssertionError(f"Unexpected repos: {repos}")

    with patch("playbook.playgrounds.list_conflict_records", side_effect=fake_list_conflict_records):
        playgrounds = load_playbook(str(playbook_path))

    assert playgrounds == [
        Playground(
            repo_name="example/content-only.git",
            merge_sha="content1",
            conflict_type="CONFLICT (contents)",
            conflict_types=("CONFLICT (contents)",),
        ),
        Playground(
            repo_name="example/content-only.git",
            merge_sha="content2",
            conflict_type="CONFLICT (contents)",
            conflict_types=("CONFLICT (contents)",),
        ),
        Playground(
            repo_name="example/mixed.git",
            merge_sha="rename1",
            conflict_type="CONFLICT (rename/rename)",
            conflict_types=("CONFLICT (rename/rename)",),
        ),
        Playground(
            repo_name="example/mixed.git",
            merge_sha="rename2",
            conflict_type="CONFLICT (rename/rename)",
            conflict_types=("CONFLICT (rename/rename)",),
        ),
    ]


def test_load_playbook_keeps_conflict_type_filter_when_target_percentages_are_set(tmp_path):
    playbook_path = tmp_path / "source-targets-with-filter.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-types:
      - CONFLICT (contents)
      - CONFLICT (rename/rename)
    conflict-type-percentages:
      CONFLICT (contents): 80
      CONFLICT (rename/rename): 20
  sources:
    - repo_url: https://github.com/example/project.git
      limit: 1
""",
        encoding="utf-8",
    )

    with patch(
        "playbook.playgrounds.list_conflict_records",
        return_value=[
            ConflictRecord("example/project.git", "abc123", ("CONFLICT (contents)",)),
        ],
    ) as list_conflict_records:
        playgrounds = load_playbook(str(playbook_path))

    list_conflict_records.assert_called_once_with(
        repos=["example/project.git"],
        conflict_types=["CONFLICT (contents)", "CONFLICT (rename/rename)"],
    )
    assert playgrounds == [
        Playground(
            repo_name="example/project.git",
            merge_sha="abc123",
            conflict_type="CONFLICT (contents)",
            conflict_types=("CONFLICT (contents)",),
        )
    ]


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

    with patch("playbook.playgrounds.list_conflict_records") as list_conflict_records:
        playgrounds = load_playbook(str(playbook_path))

    list_conflict_records.assert_not_called()
    assert playgrounds == [
        Playground(repo_name="example/project.git", merge_sha="abc123"),
        Playground(repo_name="example/project.git", merge_sha="def456"),
    ]


def test_load_playbook_rejects_parent_pair_overrides(tmp_path):
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

    with patch("playbook.playgrounds.list_conflict_records") as list_conflict_records:
        with pytest.raises(ValueError, match="Unsupported override_merge_shas entry"):
            load_playbook(str(playbook_path))

    list_conflict_records.assert_not_called()


def test_format_playground_summary_line_includes_conflict_types():
    playground = Playground(
        repo_name="example/project.git",
        merge_sha="abc123",
        conflict_types=("CONFLICT (contents)", "CONFLICT (rename/rename)"),
    )

    assert (
        format_playground_summary_line(playground)
        == "  - example/project.git: abc123 [CONFLICT (contents), CONFLICT (rename/rename)]"
    )


def test_format_playground_summary_line_marks_unknown_conflict_type():
    playground = Playground(repo_name="example/project.git", merge_sha="abc123")

    assert format_playground_summary_line(playground) == "  - example/project.git: abc123 [unknown]"


def test_playgrounds_cli_prints_human_readable_summary(monkeypatch, tmp_path, capsys):
    playbook_path = tmp_path / "default.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/example/project.git
      override_merge_shas:
        - abc123
        - def456
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))
    monkeypatch.setattr(
        playgrounds_module.sys,
        "argv",
        ["playbook-playgrounds", "default", "--skip", "1"],
    )

    playgrounds_module.main()

    assert capsys.readouterr().out == "Loaded 1 playgrounds:\n  - example/project.git: def456 [unknown]\n"


def test_playgrounds_cli_prints_achieved_conflict_type_targets(monkeypatch, tmp_path, capsys):
    playbook_path = tmp_path / "default.yaml"
    playbook_path.write_text(
        """
playbook:
  config:
    conflict-type-percentages:
      CONFLICT (contents): 75
      CONFLICT (rename/rename): 25
  sources:
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))
    monkeypatch.setattr(
        playgrounds_module.sys,
        "argv",
        ["playbook-playgrounds", "default", "--skip", "1"],
    )

    with patch(
        "playbook.playgrounds.list_conflict_records",
        return_value=[
            ConflictRecord("example/project.git", "content1", ("CONFLICT (contents)",)),
            ConflictRecord("example/project.git", "rename1", ("CONFLICT (rename/rename)",)),
            ConflictRecord("example/project.git", "content2", ("CONFLICT (contents)",)),
        ],
    ):
        playgrounds_module.main()

    assert capsys.readouterr().out == (
        "Loaded 2 playgrounds:\n"
        "  - example/project.git: rename1 [CONFLICT (rename/rename)]\n"
        "  - example/project.git: content2 [CONFLICT (contents)]\n"
        "ConflictTypeTargets achieved:\n"
        "  - CONFLICT (contents): 1/2 (50.0%; target 75.0%)\n"
        "  - CONFLICT (rename/rename): 1/2 (50.0%; target 25.0%)\n"
    )


def test_validate_playground_setup_rejects_uninitialized_submodules(monkeypatch, tmp_path):
    playground = tmp_path / "playgrounds" / "example-project-abc123"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(tmp_path / "playgrounds"))

    def fake_capture_git(*args, **kwargs):
        if args[2] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[2:5] == ("submodule", "status", "--recursive"):
            return subprocess.CompletedProcess(args, 0, stdout="-abc123 deps/sub\n", stderr="")
        raise AssertionError(f"Unexpected command: {args}")

    with patch("playbook.start.capture_git", side_effect=fake_capture_git):
        with pytest.raises(RuntimeError, match="uninitialized submodules"):
            validate_playground_setup("example-project-abc123")


def test_collect_proposed_resolution_records_error_when_branches_not_merged(monkeypatch, tmp_path):
    playgrounds = tmp_path / "playgrounds"
    playgrounds.mkdir()
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    def fake_capture_git(*args, **kwargs):
        if args[2:] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="resolved123\n", stderr="")
        if args[2:] == ("show", "-s", "--format=%P", "actual456"):
            return subprocess.CompletedProcess(args, 0, stdout="left123 right456\n", stderr="")
        if args[2:] == ("show", "-s", "--format=%P", "resolved123"):
            return subprocess.CompletedProcess(args, 0, stdout="right456\n", stderr="")
        raise AssertionError(f"Unexpected git command: {args}")

    with patch("playbook.start.capture_git", side_effect=fake_capture_git):
        with patch("playbook.start.subprocess.run") as run:
            proposed_resolution = collect_proposed_resolution("example-project-actual456")

    run.assert_not_called()
    assert proposed_resolution.commit_sha == "resolved123"
    assert proposed_resolution.actual_resolution_sha == "actual456"
    assert proposed_resolution.git_archive is None
    assert proposed_resolution.error == (
        "Resolved HEAD did not merge the expected branches: "
        "expected parents left123 and right456; got right456"
    )


def test_collect_proposed_resolution_archives_when_expected_branches_are_merged(monkeypatch, tmp_path):
    playgrounds = tmp_path / "playgrounds"
    playgrounds.mkdir()
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    def fake_capture_git(*args, **kwargs):
        if args[2:] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="resolved123\n", stderr="")
        if args[2:] == ("show", "-s", "--format=%P", "actual456"):
            return subprocess.CompletedProcess(args, 0, stdout="left123 right456\n", stderr="")
        if args[2:] == ("show", "-s", "--format=%P", "resolved123"):
            return subprocess.CompletedProcess(args, 0, stdout="right456 left123\n", stderr="")
        raise AssertionError(f"Unexpected git command: {args}")

    with patch("playbook.start.capture_git", side_effect=fake_capture_git):
        with patch(
            "playbook.start.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["playground-save", "example-project-actual456"],
                0,
                stdout="archive\n",
                stderr="",
            ),
        ) as run:
            proposed_resolution = collect_proposed_resolution("example-project-actual456")

    run.assert_called_once_with(
        ["playground-save", "example-project-actual456"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proposed_resolution.commit_sha == "resolved123"
    assert proposed_resolution.actual_resolution_sha == "actual456"
    assert proposed_resolution.git_archive == "archive"
    assert proposed_resolution.error is None


def test_save_resolution_adds_hook_error_to_failed_proposed_resolution():
    redis = FakeRedis()
    active_playground_key = "runtime:active_playground:example-project-actual456"
    redis.json().set(
        active_playground_key,
        "$",
        json.loads(
            ActivePlayground(
                playground_name="example-project-actual456",
                configuration=Configuration(
                    hook_type="opencode",
                    playground_version="test",
                    volume_type="bind-mount",
                    resolution_start=datetime(2026, 1, 1),
                ),
                hook_result={
                    "message": "Error: Configuration is invalid at .opencode/opencode.json",
                    "opencode_exit_code": 1,
                },
            ).model_dump_json()
        ),
    )

    with patch(
        "playbook.start.collect_proposed_resolution",
        return_value=ProposedResolution(
            commit_sha="resolved123",
            actual_resolution_sha="actual456",
            error="Resolved HEAD did not merge the expected branches: expected parents left123 and right456; got right456",
        ),
    ):
        resolution_key = save_resolution(redis, "example-project-actual456", active_playground_key)

    saved = redis.json().get(resolution_key)
    assert saved["hook_result"] == {
        "message": "Error: Configuration is invalid at .opencode/opencode.json",
        "opencode_exit_code": 1,
    }
    proposed_resolution = saved["proposed_resolution"]
    assert proposed_resolution["git_archive"] is None
    assert "Configuration is invalid" in proposed_resolution["error"]
    assert "Resolved HEAD did not merge the expected branches" in proposed_resolution["error"]


def test_save_resolution_does_not_add_hook_error_to_archived_proposed_resolution():
    redis = FakeRedis()
    active_playground_key = "runtime:active_playground:example-project-actual456"
    redis.json().set(
        active_playground_key,
        "$",
        json.loads(
            ActivePlayground(
                playground_name="example-project-actual456",
                configuration=Configuration(
                    hook_type="opencode",
                    playground_version="test",
                    volume_type="bind-mount",
                    resolution_start=datetime(2026, 1, 1),
                ),
                hook_result={
                    "message": "Error: Configuration is invalid at .opencode/opencode.json",
                    "opencode_exit_code": 1,
                },
            ).model_dump_json()
        ),
    )

    with patch(
        "playbook.start.collect_proposed_resolution",
        return_value=ProposedResolution(
            commit_sha="resolved123",
            actual_resolution_sha="actual456",
            git_archive="archive.tar",
        ),
    ):
        resolution_key = save_resolution(redis, "example-project-actual456", active_playground_key)

    proposed_resolution = redis.json().get(resolution_key)["proposed_resolution"]
    assert proposed_resolution["git_archive"] == "archive.tar"
    assert proposed_resolution["error"] is None


def test_process_playground_does_not_dispatch_hook_when_setup_validation_fails():
    redis = FakeRedis()
    playground = Playground(repo_name="example/project.git", merge_sha="abc123")

    def fake_run(args, **kwargs):
        if args[:1] == ["playground-setup"]:
            return subprocess.CompletedProcess(args, 0, stdout="example-project-abc123\n", stderr="")
        raise AssertionError(f"Unexpected command after bad setup: {args}")

    with patch("playbook.start.subprocess.run", side_effect=fake_run):
        with patch("playbook.start.validate_playground_setup", side_effect=RuntimeError("bad playground")):
            success = process_playground(playground, redis, 1, 1)

    assert success is False
    assert redis.json_api.set_calls == []
    assert redis.deleted == []


def test_process_playground_removes_created_playground_name():
    redis = FakeRedis()
    playground = Playground(repo_name="example/project.git", merge_sha="abc123")
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args[:1] == ["playground-setup"]:
            return subprocess.CompletedProcess(args, 0, stdout="example-project-abc123\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch("playbook.start.subprocess.run", side_effect=fake_run):
        with patch("playbook.start.validate_playground_setup"):
            success = process_playground(playground, redis, 1, 1)

    assert success is True
    assert ["hook-dispatch-task", "example-project-abc123"] in commands
    assert ["playground-rm", "example-project-abc123"] in commands
    assert ["playground-rm", "example/project.git"] not in commands
