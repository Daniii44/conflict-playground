from repo import size


def test_github_repo_from_url_supports_https_and_ssh_urls():
    assert size.github_repo_from_url("https://github.com/octocat/hello-world.git") == size.GitHubRepo(
        owner="octocat",
        name="hello-world",
    )
    assert size.github_repo_from_url("git@github.com:google/googletest.git") == size.GitHubRepo(
        owner="google",
        name="googletest",
    )


def test_unique_github_repos_deduplicates_case_insensitively():
    repos = size.unique_github_repos(
        [
            "https://github.com/octocat/hello-world.git",
            "https://github.com/Octocat/hello-world.git",
            "https://github.com/facebook/react.git",
        ]
    )

    assert repos == [
        size.GitHubRepo(owner="octocat", name="hello-world"),
        size.GitHubRepo(owner="facebook", name="react"),
    ]


def test_github_repo_from_url_rejects_non_github_hosts():
    assert size.github_repo_from_url("https://gitlab.com/octocat/hello-world.git") is None
    assert size.github_repo_from_url("git@gitlab.com:octocat/hello-world.git") is None


def test_github_token_reads_dedicated_graphql_token(monkeypatch):
    monkeypatch.setenv("GH_GRAPHQL_TOKEN", "token")

    assert size.github_token() == "token"


def test_build_disk_usage_query_uses_graphql_aliases():
    query = size.build_disk_usage_query(
        [
            size.GitHubRepo(owner="octocat", name="hello-world"),
            size.GitHubRepo(owner="google", name="googletest"),
        ]
    )

    assert 'repo0: repository(owner: "octocat", name: "hello-world")' in query
    assert 'repo1: repository(owner: "google", name: "googletest")' in query
    assert "diskUsage" in query


def test_fetch_disk_usage_maps_graphql_aliases(monkeypatch):
    def fake_graphql_request(query, token):
        assert token == "token"
        return {
            "data": {
                "repo0": {"nameWithOwner": "octocat/hello-world", "diskUsage": 10},
                "repo1": {"nameWithOwner": "google/googletest", "diskUsage": 20},
            }
        }

    monkeypatch.setattr(size, "graphql_request", fake_graphql_request)

    usages = size.fetch_disk_usage(
        [
            size.GitHubRepo(owner="octocat", name="hello-world"),
            size.GitHubRepo(owner="google", name="googletest"),
        ],
        "token",
    )

    assert usages == [
        size.RepoDiskUsage(size.GitHubRepo(owner="octocat", name="hello-world"), 10),
        size.RepoDiskUsage(size.GitHubRepo(owner="google", name="googletest"), 20),
    ]
