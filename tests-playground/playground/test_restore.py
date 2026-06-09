from pathlib import Path

import pytest

from playground.restore import resolve_playground_path


def test_resolve_playground_path_uses_playgrounds_env(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    assert resolve_playground_path("owner/repo.git-20260609T120000.000000Z-abc123") == Path(
        "/playgrounds/owner/repo.git-20260609T120000.000000Z-abc123"
    )


def test_resolve_playground_path_rejects_absolute_paths(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with pytest.raises(RuntimeError, match="playground name"):
        resolve_playground_path("/tmp/playground")


def test_resolve_playground_path_requires_playgrounds_env(monkeypatch):
    monkeypatch.delenv("PLAYGROUNDS", raising=False)

    with pytest.raises(RuntimeError, match="PLAYGROUNDS"):
        resolve_playground_path("owner/repo.git-abc123")
