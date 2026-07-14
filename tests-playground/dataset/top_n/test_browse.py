import argparse
import importlib.util
from pathlib import Path
import requests


def load_browse_module():
    module_path = Path(__file__).parents[3] / "src-playground" / "dataset" / "top-n" / "browse.py"
    spec = importlib.util.spec_from_file_location("dataset_top_n_browse", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_positive_float_accepts_positive_values():
    browse = load_browse_module()

    assert browse.positive_float("1") == 1
    assert browse.positive_float("1.5") == 1.5


def test_positive_float_rejects_non_positive_values():
    browse = load_browse_module()

    for value in ["0", "-1"]:
        try:
            browse.positive_float(value)
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"expected {value} to be rejected")


def test_get_popular_repos_skips_repos_larger_than_max_size(monkeypatch):
    browse = load_browse_module()
    pages = [
        [
            {
                "full_name": "large/repo",
                "stargazers_count": 30_000,
                "clone_url": "https://github.com/large/repo.git",
                "size": 2 * 1024 * 1024,
            },
            {
                "full_name": "small/repo",
                "stargazers_count": 20_000,
                "clone_url": "https://github.com/small/repo.git",
                "size": 512 * 1024,
                "default_branch": "main",
            },
        ],
        [
            {
                "full_name": "another/small",
                "stargazers_count": 10_000,
                "clone_url": "https://github.com/another/small.git",
                "size": 1024 * 1024,
                "default_branch": "master",
            },
        ],
    ]
    requested_pages = []
    requested_gitmodules = []

    class FakeResponse:
        def __init__(self, *, items=None, status_code=200):
            self.items = items
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(f"status={self.status_code}")

        def json(self):
            return {"items": self.items}

    def fake_get(url, params, headers):
        if url == "https://api.github.com/search/repositories":
            requested_pages.append(params["page"])
            return FakeResponse(items=pages[params["page"] - 1])

        requested_gitmodules.append((url, params["ref"]))
        if url.endswith("/small/repo/contents/.gitmodules"):
            return FakeResponse(status_code=200)
        if url.endswith("/another/small/contents/.gitmodules"):
            return FakeResponse(status_code=404)

        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(browse.requests, "get", fake_get)

    repos = browse.get_popular_repos(limit=2, max_size_gb=1)

    assert requested_pages == [1, 2]
    assert requested_gitmodules == [
        ("https://api.github.com/repos/small/repo/contents/.gitmodules", "main"),
        ("https://api.github.com/repos/another/small/contents/.gitmodules", "master"),
    ]
    assert [repo["full_name"] for repo in repos] == ["small/repo", "another/small"]
    assert [repo["uses_submodules_in_head"] for repo in repos] == [True, False]


def test_repo_uses_submodules_in_head_when_gitmodules_exists(monkeypatch):
    browse = load_browse_module()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    def fake_get(url, params, headers):
        assert url == "https://api.github.com/repos/owner/repo/contents/.gitmodules"
        assert params == {"ref": "main"}
        return FakeResponse()

    monkeypatch.setattr(browse.requests, "get", fake_get)

    assert browse.repo_uses_submodules_in_head(
        "owner/repo",
        headers={"Accept": "application/json"},
        default_branch="main",
    )


def test_repo_uses_submodules_in_head_when_gitmodules_missing(monkeypatch):
    browse = load_browse_module()

    class FakeResponse:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("404 response should not raise")

    monkeypatch.setattr(browse.requests, "get", lambda url, params, headers: FakeResponse())

    assert not browse.repo_uses_submodules_in_head(
        "owner/repo",
        headers={"Accept": "application/json"},
        default_branch="main",
    )
