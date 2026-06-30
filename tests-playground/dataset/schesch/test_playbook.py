import json
from pathlib import Path

import pytest

from common.merge_tree import ConflictType, MergeLogicalConflict
from dataset.schesch.playbook import (
    PlaybookCandidate,
    build_schesch_playbook,
    build_schesch_playbook_result,
    build_schesch_raw_playbook,
    build_schesch_raw_playbook_result,
    generate_schesch_playbooks,
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


@pytest.fixture(autouse=True)
def cached_repos(monkeypatch):
    monkeypatch.setattr("dataset.schesch.playbook.repo_is_cached", lambda _repo: True)


def qualifying_merge():
    return {
        "diff contains java file": True,
        "test merge": True,
        "parents pass": True,
        "left parent test result": "Tests_passed",
        "right parent test result": "Tests_passed",
        "num_diff_files": 2,
        "num_diff_hunks": 1,
    }


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def content_conflict() -> MergeLogicalConflict:
    return MergeLogicalConflict(
        type=ConflictType.CONFLICT_CONTENTS,
        info="CONFLICT (content): Merge conflict in file.java",
        paths=["file.java"],
    )


def add_add_conflict() -> MergeLogicalConflict:
    return MergeLogicalConflict(
        type=ConflictType.CONFLICT_CONTENTS,
        info="CONFLICT (add/add): Merge conflict in file.java",
        paths=["file.java"],
    )


def rename_conflict() -> MergeLogicalConflict:
    return MergeLogicalConflict(
        type=ConflictType.CONFLICT_RENAME_RENAME,
        info="CONFLICT (rename/rename): Rename conflict",
        paths=["file.java"],
    )


def schesch_info(
    *,
    human_passed: bool = True,
    parent_passes: tuple[bool, bool] = (True, True),
    build_tool: str = "maven",
    java_home: str = "/opt/java/openjdk-8",
    parent_build_tools: tuple[str, str] | None = None,
    parent_java_homes: tuple[str, str] | None = None,
) -> dict:
    parent_build_tools = parent_build_tools or (build_tool, build_tool)
    parent_java_homes = parent_java_homes or (java_home, java_home)
    return {
        "human": {
            "label": "human",
            "passed": human_passed,
            "build_tool": build_tool,
            "successful_java_home": java_home,
        },
        "parents": [
            {
                "label": "parent-1",
                "passed": parent_passes[0],
                "build_tool": parent_build_tools[0],
                "successful_java_home": parent_java_homes[0],
            },
            {
                "label": "parent-2",
                "passed": parent_passes[1],
                "build_tool": parent_build_tools[1],
                "successful_java_home": parent_java_homes[1],
            },
        ],
    }


def schesch_info_values(candidates: list[PlaybookCandidate]) -> dict:
    return {
        f"info:conflict:schesch:{candidate.repo}:{candidate.merge_sha}": schesch_info()
        for candidate in candidates
    }


def test_build_schesch_playbook_resolves_unique_merge_commits_by_repo(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left2_right2": qualifying_merge(),
            "left1_right1": qualifying_merge(),
            "left4_right4": qualifying_merge(),
            "left3_right3": qualifying_merge() | {"parents pass": False},
        },
    )
    write_json(
        root / "other" / "project.json",
        {
            "left4_right4": qualifying_merge(),
        },
    )

    def fake_merge_parent_index(repo):
        return {
            "other/project.git": {
                frozenset(("left4", "right4")): ["merge4"],
            },
            "owner/repo.git": {
                frozenset(("left1", "right1")): ["merge1"],
                frozenset(("left2", "right2")): ["merge2a", "merge2b"],
            },
        }[repo]

    monkeypatch.setattr("dataset.schesch.playbook.merge_parent_index", fake_merge_parent_index)
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    playbook = build_schesch_raw_playbook(root)

    assert playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/other/project.git",
                    "override_merge_shas": [
                        "merge4",
                    ],
                },
                {
                    "repo_url": "https://github.com/owner/repo.git",
                    "override_merge_shas": [
                        "merge1",
                    ],
                },
            ]
        }
    }


def test_build_schesch_playbook_filters_non_maven_and_non_content_conflicts(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": qualifying_merge(),
            "left3_right3": qualifying_merge(),
            "left4_right4": qualifying_merge(),
            "left5_right5": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset(("left1", "right1")): ["keep"],
            frozenset(("left2", "right2")): ["non-maven"],
            frozenset(("left3", "right3")): ["rename-conflict"],
            frozenset(("left4", "right4")): ["no-conflict"],
            frozenset(("left5", "right5")): ["add-add-conflict"],
        },
    )
    monkeypatch.setattr(
        "dataset.schesch.playbook.has_top_level_pom",
        lambda _repo, merge_sha: merge_sha != "non-maven",
    )
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, left_parent, _right_parent: {
            "left1": (content_conflict(),),
            "left3": (content_conflict(), rename_conflict()),
            "left4": tuple(),
            "left5": (add_add_conflict(),),
        }[left_parent],
    )

    result = build_schesch_raw_playbook_result(root)

    assert result.playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/owner/repo.git",
                    "override_merge_shas": ["keep"],
                },
            ]
        }
    }
    assert result.non_maven_merges == 1
    assert result.non_content_conflict_merges == 2
    assert result.no_content_conflict_merges == 1


def test_build_schesch_playbook_does_not_require_core_conflict_info(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset(("left1", "right1")): ["keep"],
            frozenset(("left2", "right2")): ["missing-info"],
        },
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    result = build_schesch_raw_playbook_result(root)

    assert result.playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/owner/repo.git",
                    "override_merge_shas": ["keep", "missing-info"],
                },
            ]
        }
    }


def test_build_schesch_playbook_filters_uncached_repositories(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "cached" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
        },
    )
    write_json(
        root / "missing" / "repo.json",
        {
            "left2_right2": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.repo_is_cached",
        lambda repo: repo == "cached/repo.git",
    )

    def fake_merge_parent_index(repo):
        assert repo == "cached/repo.git"
        return {
            frozenset(("left1", "right1")): ["merge1"],
        }

    monkeypatch.setattr("dataset.schesch.playbook.merge_parent_index", fake_merge_parent_index)
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    result = build_schesch_raw_playbook_result(root)

    assert result.playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/cached/repo.git",
                    "override_merge_shas": ["merge1"],
                },
            ]
        }
    }
    assert result.skipped_repos == {"missing/repo.git"}


def test_build_schesch_playbook_applies_global_random_limit(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            f"left{index}_right{index}": qualifying_merge()
            for index in range(5)
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset((f"left{index}", f"right{index}")): [f"merge{index}"]
            for index in range(5)
        },
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    raw_result = build_schesch_raw_playbook_result(root)
    result = build_schesch_playbook_result(
        raw_result,
        limit=2,
        seed=7,
        redis=FakeRedis(schesch_info_values(raw_result.candidates)),
    )
    selected_shas = result.playbook["playbook"]["sources"][0]["override_merge_shas"]

    assert len(selected_shas) == 2
    assert set(selected_shas) <= {f"merge{index}" for index in range(5)}
    assert result.sampled_out_merges == 3


def test_build_schesch_playbook_filters_by_schesch_info(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": qualifying_merge(),
            "left3_right3": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset(("left1", "right1")): ["keep"],
            frozenset(("left2", "right2")): ["human-fails"],
            frozenset(("left3", "right3")): ["parent-fails"],
        },
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    raw_result = build_schesch_raw_playbook_result(root)
    result = build_schesch_playbook_result(
        raw_result,
        redis=FakeRedis(
            {
                "info:conflict:schesch:owner/repo.git:keep": schesch_info(),
                "info:conflict:schesch:owner/repo.git:human-fails": schesch_info(human_passed=False),
                "info:conflict:schesch:owner/repo.git:parent-fails": schesch_info(parent_passes=(True, False)),
            }
        ),
    )

    assert result.playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/owner/repo.git",
                    "override_merge_shas": ["keep"],
                },
            ]
        }
    }
    assert result.missing_schesch_info_merges == 0
    assert result.failed_schesch_info_merges == 2


def test_build_schesch_playbook_requires_same_schesch_environment(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": qualifying_merge(),
            "left3_right3": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset(("left1", "right1")): ["keep"],
            frozenset(("left2", "right2")): ["build-tool-mismatch"],
            frozenset(("left3", "right3")): ["java-mismatch"],
        },
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    raw_result = build_schesch_raw_playbook_result(root)
    result = build_schesch_playbook_result(
        raw_result,
        redis=FakeRedis(
            {
                "info:conflict:schesch:owner/repo.git:keep": schesch_info(),
                "info:conflict:schesch:owner/repo.git:build-tool-mismatch": schesch_info(
                    parent_build_tools=("gradle", "maven")
                ),
                "info:conflict:schesch:owner/repo.git:java-mismatch": schesch_info(
                    parent_java_homes=("/opt/java/openjdk-8", "/opt/java/openjdk-11")
                ),
            }
        ),
    )

    assert result.playbook["playbook"]["sources"][0]["override_merge_shas"] == ["keep"]
    assert result.inconsistent_schesch_environment_merges == 2


def test_build_schesch_playbook_reports_missing_schesch_info(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {
            frozenset(("left1", "right1")): ["keep"],
            frozenset(("left2", "right2")): ["missing-info"],
        },
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    raw_result = build_schesch_raw_playbook_result(root)
    result = build_schesch_playbook_result(
        raw_result,
        redis=FakeRedis({"info:conflict:schesch:owner/repo.git:keep": schesch_info()}),
    )

    assert result.missing_schesch_info_merges == 1


def test_generate_schesch_playbooks_writes_raw_but_not_final_when_info_is_missing(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    raw_output = tmp_path / "schesch-raw.yaml"
    output = tmp_path / "schesch.yaml"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {frozenset(("left1", "right1")): ["missing-info"]},
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    raw_result, result = generate_schesch_playbooks(
        root,
        raw_output,
        output,
        redis=FakeRedis({}),
    )

    assert raw_output.is_file()
    assert "missing-info" in raw_output.read_text(encoding="utf-8")
    assert not output.exists()
    assert len(raw_result.candidates) == 1
    assert result is not None
    assert result.missing_schesch_info_merges == 1


def test_build_schesch_playbook_raises_when_schesch_info_is_missing(monkeypatch, tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
        },
    )

    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_parent_index",
        lambda _repo: {frozenset(("left1", "right1")): ["missing-info"]},
    )
    monkeypatch.setattr("dataset.schesch.playbook.has_top_level_pom", lambda _repo, _merge_sha: True)
    monkeypatch.setattr(
        "dataset.schesch.playbook.merge_logical_conflicts",
        lambda _repo, _left_parent, _right_parent: (content_conflict(),),
    )

    with pytest.raises(RuntimeError, match="Missing info:conflict:schesch"):
        build_schesch_playbook(root, redis=FakeRedis({}))
