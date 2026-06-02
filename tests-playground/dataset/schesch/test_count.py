import json
from pathlib import Path

from dataset.schesch.count import count_merge_analysis, parse_merge_analysis_key


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def test_parse_merge_analysis_key_splits_parent_pair():
    assert parse_merge_analysis_key("left_right") == ("left", "right")
    assert parse_merge_analysis_key("left") is None


def test_count_merge_analysis_counts_only_qualifying_merges(tmp_path):
    root = tmp_path / "merge_analysis"
    non_java = qualifying_merge() | {"diff contains java file": False}
    parent_failed = qualifying_merge() | {
        "parents pass": False,
        "right parent test result": "Tests_failed",
    }
    not_tested_merge = qualifying_merge() | {"test merge": False}
    large_diff = qualifying_merge() | {"num_diff_files": 1000}
    errored_hunks = qualifying_merge() | {"num_diff_hunks": "Error"}
    write_json(
        root / "owner" / "repo.json",
        {
            "left1_right1": qualifying_merge(),
            "left2_right2": non_java,
            "left3_right3": parent_failed,
            "left4_right4": not_tested_merge,
            "left5_right5": large_diff,
            "left6_right6": errored_hunks,
        },
    )
    write_json(
        root / "other" / "project.json",
        {
            "left1_right1": qualifying_merge(),
        },
    )

    counts = count_merge_analysis(root)

    assert counts.distinct_repos == 2
    assert counts.distinct_merges == 2


def test_count_merge_analysis_skips_repos_without_qualifying_merges(tmp_path):
    root = tmp_path / "merge_analysis"
    write_json(root / "owner" / "empty.json", {})
    write_json(root / "owner" / "repo.json", {"left_right": qualifying_merge()})
    write_json(
        root / "other" / "project.json",
        {"left_right": qualifying_merge() | {"diff contains java file": False}},
    )

    counts = count_merge_analysis(root)

    assert counts.distinct_repos == 1
    assert counts.distinct_merges == 1
