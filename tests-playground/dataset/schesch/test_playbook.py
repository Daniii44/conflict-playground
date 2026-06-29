import json
from pathlib import Path

from dataset.schesch.playbook import build_schesch_playbook


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

    playbook = build_schesch_playbook(root)

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
