from subprocess import CompletedProcess
from unittest.mock import patch

from info.conflict import sync as conflict_sync


def test_collect_analysis_candidates_uses_override_shas_without_rev_list():
    with patch("info.conflict.sync.capture_git") as capture_git:
        candidates = conflict_sync.collect_analysis_candidates(
            "/repos/example.git",
            "owner/repo.git",
            ["merge1", "merge2"],
        )

    capture_git.assert_not_called()
    assert [candidate.merge_commit_oid for candidate in candidates] == ["merge1", "merge2"]
    assert all(candidate.git_dir == "/repos/example.git" for candidate in candidates)
    assert all(candidate.git_repo_name == "owner/repo.git" for candidate in candidates)


def test_collect_analysis_candidates_falls_back_to_rev_list_without_overrides():
    with patch("info.conflict.sync.capture_git") as capture_git:
        capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="merge1\nmerge2\n", stderr="")

        candidates = conflict_sync.collect_analysis_candidates("/repos/example.git", "owner/repo.git")

    capture_git.assert_called_once_with(
        "--git-dir=/repos/example.git",
        "rev-list",
        "--merges",
        "HEAD",
        check=False,
    )
    assert [candidate.merge_commit_oid for candidate in candidates] == ["merge1", "merge2"]


def test_collect_playbook_override_merge_shas_uses_only_matching_repo_overrides(tmp_path):
    playbook_path = tmp_path / "sample.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/owner/repo.git
      override_merge_shas:
        - merge1
        - merge2
    - repo_url: https://github.com/owner/dynamic.git
      limit: 50
    - repo_url: https://github.com/other/repo.git
      override_merge_shas:
        - other-merge
""",
        encoding="utf-8",
    )

    assert conflict_sync.collect_playbook_override_merge_shas(
        playbook_path,
        "owner/repo.git",
    ) == ["merge1", "merge2"]
    assert conflict_sync.collect_playbook_override_merge_shas(
        playbook_path,
        "owner/dynamic.git",
    ) is None


def test_collect_playbook_override_merge_shas_resolves_parent_pairs(tmp_path):
    playbook_path = tmp_path / "sample.yaml"
    playbook_path.write_text(
        """
playbook:
  sources:
    - repo_url: https://github.com/owner/repo.git
      override_merge_shas:
        - parents:
            - left
            - right
""",
        encoding="utf-8",
    )

    with patch("info.conflict.sync.resolve_playground_merge_sha", return_value="resolved") as resolve:
        result = conflict_sync.collect_playbook_override_merge_shas(playbook_path, "owner/repo.git")

    assert result == ["resolved"]
    playground = resolve.call_args.args[0]
    assert playground.repo_name == "owner/repo.git"
    assert playground.parent_shas == ("left", "right")
