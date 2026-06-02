import argparse
import subprocess

import sync as root_sync
from repo import sync as repo_sync


def successful_git_result(args=None):
    return argparse.Namespace(returncode=0, args=args or ["git"])


def test_repo_sync_skips_submodule_discovery_when_disabled(monkeypatch, tmp_path):
    submodule_discovery_called = False

    def fake_gitmodules_blobs(repo_path, breadcrumbs):
        nonlocal submodule_discovery_called
        submodule_discovery_called = True
        return []

    monkeypatch.setattr(repo_sync, "stream_git", lambda *args, **kwargs: successful_git_result(args))
    monkeypatch.setattr(repo_sync, "gitmodules_blobs", fake_gitmodules_blobs)

    sync = repo_sync.RepoSync(tmp_path, sync_submodules=False)
    sync.sync_repo("https://github.com/example/project.git", required=True, breadcrumbs=())

    assert not submodule_discovery_called


def test_repo_sync_discovers_submodules_by_default(monkeypatch, tmp_path):
    synced_urls = []

    def fake_stream_git(*args, **kwargs):
        return successful_git_result(list(args))

    def fake_gitmodules_blobs(repo_path, breadcrumbs):
        return ["blob"] if breadcrumbs == ("example/project.git",) else []

    def fake_submodule_urls(repo_path, blob, breadcrumbs):
        return ["https://github.com/example/lib.git"]

    monkeypatch.setattr(repo_sync, "stream_git", fake_stream_git)
    monkeypatch.setattr(repo_sync, "gitmodules_blobs", fake_gitmodules_blobs)
    monkeypatch.setattr(repo_sync, "submodule_urls", fake_submodule_urls)

    original_sync_repo = repo_sync.RepoSync.sync_repo

    def tracking_sync_repo(self, url, *, required, breadcrumbs):
        synced_urls.append(url)
        return original_sync_repo(self, url, required=required, breadcrumbs=breadcrumbs)

    monkeypatch.setattr(repo_sync.RepoSync, "sync_repo", tracking_sync_repo)

    sync = repo_sync.RepoSync(tmp_path)
    sync.sync_repo("https://github.com/example/project.git", required=True, breadcrumbs=())

    assert synced_urls == [
        "https://github.com/example/project.git",
        "https://github.com/example/lib.git",
    ]


def test_root_sync_passes_no_submodules_to_repo_sync():
    args = argparse.Namespace(playbook="schesch", no_submodules=True)

    assert root_sync.build_repo_args(args) == ["--no-submodules", "schesch"]


def test_repo_sync_main_continues_after_failed_required_repo(monkeypatch, tmp_path):
    playbook_path = tmp_path / "playbook.yaml"
    playbook_path.write_text("playbook: {}\n", encoding="utf-8")
    synced_urls = []

    monkeypatch.setenv("CACHES", str(tmp_path / "caches"))
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))
    monkeypatch.setattr(repo_sync, "parse_args", lambda: argparse.Namespace(playbook=str(playbook_path), no_submodules=True))
    monkeypatch.setattr(
        repo_sync,
        "load_playbook_repo_urls",
        lambda path: [
            "https://github.com/example/inaccessible.git",
            "https://github.com/example/accessible.git",
        ],
    )

    def fake_sync_repo(self, url, *, required, breadcrumbs):
        synced_urls.append(url)
        if "inaccessible" in url:
            raise subprocess.CalledProcessError(128, ["git", "clone", "--bare", url])

    monkeypatch.setattr(repo_sync.RepoSync, "sync_repo", fake_sync_repo)

    exit_code = repo_sync.main()

    assert exit_code == 1
    assert synced_urls == [
        "https://github.com/example/inaccessible.git",
        "https://github.com/example/accessible.git",
    ]
