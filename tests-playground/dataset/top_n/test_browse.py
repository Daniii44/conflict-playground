import argparse
import importlib.util
from pathlib import Path


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
            },
        ],
        [
            {
                "full_name": "another/small",
                "stargazers_count": 10_000,
                "clone_url": "https://github.com/another/small.git",
                "size": 1024 * 1024,
            },
        ],
    ]
    requested_pages = []

    class FakeResponse:
        def __init__(self, items):
            self.items = items

        def raise_for_status(self):
            pass

        def json(self):
            return {"items": self.items}

    def fake_get(url, params, headers):
        requested_pages.append(params["page"])
        return FakeResponse(pages[params["page"] - 1])

    monkeypatch.setattr(browse.requests, "get", fake_get)

    repos = browse.get_popular_repos(limit=2, max_size_gb=1)

    assert requested_pages == [1, 2]
    assert [repo["full_name"] for repo in repos] == ["small/repo", "another/small"]
