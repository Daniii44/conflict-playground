from info.submodule.playbook import (
    build_playbook_yaml,
    collect_submodule_playbook_sources,
)


class FakeRedisJson:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values):
        self.json_api = FakeRedisJson(values)

    def json(self):
        return self.json_api


def submodule_node(repo, *, url=None, unavailable=False, submodules=None):
    return {
        "repo": repo,
        "url": url or f"https://github.com/{repo}",
        "unavailable": unavailable,
        "submodules": submodules or [],
    }


def submodule(repo, *, unavailable=False, present_in_head=True):
    return {
        "repo": repo,
        "name": repo.rsplit("/", 1)[-1],
        "path": repo.rsplit("/", 1)[-1].removesuffix(".git"),
        "url": f"https://github.com/{repo}",
        "resolved_url": f"https://github.com/{repo}",
        "unavailable": unavailable,
        "present_in_head": present_in_head,
    }


def info_key(repo):
    return f"info:submodule:{repo}"


def test_collect_submodule_playbook_sources_includes_nested_submodule_owners():
    redis = FakeRedis(
        {
            info_key("owner/root.git"): submodule_node(
                "owner/root.git",
                submodules=[
                    submodule("owner/child.git"),
                    submodule("owner/unavailable.git", unavailable=True),
                ],
            ),
            info_key("owner/child.git"): submodule_node(
                "owner/child.git",
                url="git@github.com:owner/child.git",
                submodules=[submodule("owner/grandchild.git")],
            ),
            info_key("owner/grandchild.git"): submodule_node("owner/grandchild.git"),
            info_key("owner/unavailable.git"): submodule_node(
                "owner/unavailable.git",
                unavailable=True,
            ),
            info_key("owner/no-submodules.git"): submodule_node("owner/no-submodules.git"),
        }
    )

    sources = collect_submodule_playbook_sources(
        redis,
        ["owner/root.git", "owner/no-submodules.git"],
    )

    assert [
        (source.repo, source.repo_url, source.available_submodule_count)
        for source in sources
    ] == [
        ("owner/child.git", "git@github.com:owner/child.git", 1),
        ("owner/root.git", "https://github.com/owner/root.git", 1),
    ]


def test_collect_submodule_playbook_sources_handles_cycles():
    redis = FakeRedis(
        {
            info_key("owner/a.git"): submodule_node(
                "owner/a.git",
                submodules=[submodule("owner/b.git")],
            ),
            info_key("owner/b.git"): submodule_node(
                "owner/b.git",
                submodules=[submodule("owner/a.git")],
            ),
        }
    )

    sources = collect_submodule_playbook_sources(redis, ["owner/a.git"])

    assert [source.repo for source in sources] == ["owner/a.git", "owner/b.git"]


def test_collect_submodule_playbook_sources_respects_head_only():
    redis = FakeRedis(
        {
            info_key("owner/root.git"): submodule_node(
                "owner/root.git",
                submodules=[
                    submodule("owner/historical.git", present_in_head=False),
                    submodule("owner/head.git", present_in_head=True),
                ],
            ),
            info_key("owner/historical.git"): submodule_node(
                "owner/historical.git",
                submodules=[submodule("owner/historical-child.git")],
            ),
            info_key("owner/historical-child.git"): submodule_node("owner/historical-child.git"),
            info_key("owner/head.git"): submodule_node("owner/head.git"),
        }
    )

    sources = collect_submodule_playbook_sources(
        redis,
        ["owner/root.git"],
        head_only=True,
    )

    assert [source.repo for source in sources] == ["owner/root.git"]
    assert sources[0].available_submodule_count == 1


def test_build_playbook_yaml_writes_sources_and_limits():
    sources = collect_submodule_playbook_sources(
        FakeRedis(
            {
                info_key("owner/root.git"): submodule_node(
                    "owner/root.git",
                    submodules=[submodule("owner/child.git")],
                ),
                info_key("owner/child.git"): submodule_node("owner/child.git"),
            }
        ),
        ["owner/root.git"],
    )

    assert build_playbook_yaml(sources, 25) == (
        "playbook:\n"
        "  sources:\n"
        "    - repo_url: https://github.com/owner/root.git\n"
        "      limit: 25\n"
    )
