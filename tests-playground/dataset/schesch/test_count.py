import json
from pathlib import Path

from dataset.schesch.count import count_merge_timing_results, parse_merge_timing_key


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_merge_timing_key_ignores_tool_suffix():
    assert parse_merge_timing_key("left-right-gitmerge_ort") == ("left", "right")
    assert parse_merge_timing_key("left-right-tool-with-dashes") == ("left", "right")
    assert parse_merge_timing_key("left-right") is None


def test_count_merge_timing_results_counts_each_merge_once_per_repo(tmp_path):
    root = tmp_path / "merge_timing_results"
    write_json(
        root / "owner" / "repo.json",
        {
            "left1-right1-gitmerge_ort": {"run_time": [0.1]},
            "left1-right1-spork": {"run_time": [0.2]},
            "left2-right2-gitmerge_ort": {"run_time": [0.3]},
        },
    )
    write_json(
        root / "other" / "project.json",
        {
            "left1-right1-gitmerge_ort": {"run_time": [0.4]},
        },
    )

    counts = count_merge_timing_results(root)

    assert counts.distinct_repos == 2
    assert counts.distinct_merges == 3


def test_count_merge_timing_results_skips_empty_repos(tmp_path):
    root = tmp_path / "merge_timing_results"
    write_json(root / "owner" / "empty.json", {})
    write_json(root / "owner" / "repo.json", {"left-right-tool": {"run_time": [0.1]}})

    counts = count_merge_timing_results(root)

    assert counts.distinct_repos == 1
    assert counts.distinct_merges == 1
