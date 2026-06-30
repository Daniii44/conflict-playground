import argparse
import subprocess

from info import sync as info_sync


def test_info_sync_continues_after_failed_repo(monkeypatch):
    commands = []

    monkeypatch.setattr(info_sync, "list_available_analyses", lambda: ["core"])
    monkeypatch.setattr(
        info_sync,
        "parse_args",
        lambda available_analyses: argparse.Namespace(
            playbook="sample",
            analysis=None,
            all_analysis=False,
            list_analyses=False,
            max_workers=None,
            verbose=False,
        ),
    )
    monkeypatch.setattr(info_sync, "collect_repos", lambda playbook: ["missing/repo.git", "ok/repo.git"])

    def fake_run(command):
        commands.append(command)
        if command[-1] == "missing/repo.git":
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(info_sync, "run", fake_run)

    exit_code = info_sync.main()

    assert exit_code == 1
    assert commands == [
        ["info-conflict-sync", "--all-analysis", "--playbook", "sample", "missing/repo.git"],
        ["info-conflict-sync", "--all-analysis", "--playbook", "sample", "ok/repo.git"],
        ["state-clickhouse-sync"],
    ]


def test_info_sync_returns_clickhouse_failure(monkeypatch):
    monkeypatch.setattr(info_sync, "list_available_analyses", lambda: ["core"])
    monkeypatch.setattr(
        info_sync,
        "parse_args",
        lambda available_analyses: argparse.Namespace(
            playbook="sample",
            analysis=None,
            all_analysis=False,
            list_analyses=False,
            max_workers=None,
            verbose=False,
        ),
    )
    monkeypatch.setattr(info_sync, "collect_repos", lambda playbook: ["ok/repo.git"])

    def fake_run(command):
        if command == ["state-clickhouse-sync"]:
            raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(info_sync, "run", fake_run)

    assert info_sync.main() == 7


def test_info_sync_passes_verbose_to_conflict_sync(monkeypatch):
    commands = []

    monkeypatch.setattr(info_sync, "list_available_analyses", lambda: ["schesch"])
    monkeypatch.setattr(
        info_sync,
        "parse_args",
        lambda available_analyses: argparse.Namespace(
            playbook="sample",
            analysis=["schesch"],
            all_analysis=False,
            list_analyses=False,
            max_workers=1,
            verbose=True,
        ),
    )
    monkeypatch.setattr(info_sync, "collect_repos", lambda playbook: ["ok/repo.git"])
    monkeypatch.setattr(info_sync, "run", lambda command: commands.append(command))

    assert info_sync.main() == 0
    assert commands == [
        [
            "info-conflict-sync",
            "--analysis",
            "schesch",
            "--max-workers",
            "1",
            "--verbose",
            "--playbook",
            "sample",
            "ok/repo.git",
        ],
        ["state-clickhouse-sync"],
    ]
