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


def test_build_schesch_playbook_groups_qualifying_parent_pairs_by_repo(tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(
        root / "owner" / "repo.json",
        {
            "left2_right2": qualifying_merge(),
            "left1_right1": qualifying_merge(),
            "left3_right3": qualifying_merge() | {"parents pass": False},
        },
    )
    write_json(
        root / "other" / "project.json",
        {
            "left4_right4": qualifying_merge(),
        },
    )

    playbook = build_schesch_playbook(root)

    assert playbook == {
        "playbook": {
            "sources": [
                {
                    "repo_url": "https://github.com/other/project.git",
                    "override_merge_shas": [
                        {"parents": ["left4", "right4"]},
                    ],
                },
                {
                    "repo_url": "https://github.com/owner/repo.git",
                    "override_merge_shas": [
                        {"parents": ["left1", "right1"]},
                        {"parents": ["left2", "right2"]},
                    ],
                },
            ]
        }
    }
