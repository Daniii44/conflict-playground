import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import resolution

from common.active_playground_models import Configuration
from common.resolution_models import ConflictResolution, ProposedResolution


RESOLUTION_LIST_PATH = Path(resolution.__path__[0]) / "list.py"
list_spec = importlib.util.spec_from_file_location("resolution_list", RESOLUTION_LIST_PATH)
resolution_list = importlib.util.module_from_spec(list_spec)
assert list_spec.loader is not None
list_spec.loader.exec_module(resolution_list)


class FakeRedisJson:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, keys=None, values=None):
        self.keys = keys or []
        self.json_api = FakeRedisJson(values)
        self.deleted = []

    def scan_iter(self, match):
        prefix = match.removesuffix("*")
        return (key for key in self.keys if key.startswith(prefix))

    def json(self):
        return self.json_api

    def delete(self, *keys):
        self.deleted.extend(keys)
        return len(keys)


def resolution_payload(git_archive="archive"):
    return ConflictResolution(
        configuration=Configuration(
            hook_type="manual-cli",
            playground_version="test",
            volume_type="bind-mount",
            resolution_start="2026-06-01T00:00:00",
        ),
        resolution_end="2026-06-01T00:00:10",
        proposed_resolution=ProposedResolution(
            commit_sha="proposed",
            actual_resolution_sha="actual",
            git_archive=git_archive,
        ),
    ).model_dump(mode="json")


def test_list_resolution_keys_returns_sorted_resolution_keys_only():
    redis = FakeRedis(
        keys=[
            "runtime:active_playground:x",
            "resolution:conflict:owner/repo.git-b:20260609T120000.000000Z",
            "resolution:conflict:owner/repo.git-a:20260609T120000.000000Z",
        ]
    )

    assert resolution_list.list_resolution_keys(redis) == [
        "resolution:conflict:owner/repo.git-a:20260609T120000.000000Z",
        "resolution:conflict:owner/repo.git-b:20260609T120000.000000Z",
    ]


def test_restore_resolution_restores_archive_to_playground_from_key():
    from resolution.restore import restore_resolution

    key = "resolution:conflict:owner/repo.git-actual:20260609T120000.000000Z"
    redis = FakeRedis(values={key: resolution_payload(git_archive="encoded-archive")})

    with patch("resolution.restore.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")

        playground_name = restore_resolution(redis, key)

    assert playground_name == "owner/repo.git-actual"
    run.assert_called_once_with(
        ["playground-restore", "owner/repo.git-actual"],
        input="encoded-archive",
        text=True,
        capture_output=True,
        check=False,
    )


def test_exec_shell_in_playground_uses_playgrounds_env(monkeypatch):
    from resolution.restore import exec_shell_in_playground

    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    monkeypatch.setenv("SHELL", "/bin/zsh")

    with patch("resolution.restore.os.chdir") as chdir:
        with patch("resolution.restore.os.execvp") as execvp:
            exec_shell_in_playground("owner/repo.git-actual")

    chdir.assert_called_once_with(Path("/playgrounds/owner/repo.git-actual"))
    execvp.assert_called_once_with("/bin/zsh", ["/bin/zsh"])


def test_prune_resolution_deletes_one_key():
    from resolution.prune import prune_resolution

    redis = FakeRedis()
    key = "resolution:conflict:owner/repo.git-a:20260609T120000.000000Z"

    deleted = prune_resolution(redis, key=key)

    assert deleted == [key]
    assert redis.deleted == [key]


def test_prune_resolution_deletes_all_resolution_keys():
    from resolution.prune import prune_resolution

    redis = FakeRedis(
        keys=[
            "runtime:active_playground:x",
            "resolution:conflict:owner/repo.git-b:20260609T120000.000000Z",
            "resolution:conflict:owner/repo.git-a:20260609T120000.000000Z",
        ]
    )

    deleted = prune_resolution(redis, prune_all=True)

    assert deleted == [
        "resolution:conflict:owner/repo.git-a:20260609T120000.000000Z",
        "resolution:conflict:owner/repo.git-b:20260609T120000.000000Z",
    ]
    assert redis.deleted == deleted
