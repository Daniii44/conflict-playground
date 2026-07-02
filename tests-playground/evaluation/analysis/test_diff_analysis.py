from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.diff_analysis import BLANK_LINE_DIFF_MODES, WHITESPACE_DIFF_MODES, DiffEvaluationAnalysis


def evaluation_input(restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha"):
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    return EvaluationInput(
        resolution_key=resolution_key,
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name=restored_playground_name,
        resolution=ConflictResolution(
            configuration=Configuration(
                hook_type="manual-cli",
                playground_version="test",
                volume_type="bind-mount",
                resolution_start=datetime(2026, 6, 2, 12, 0, 0),
            ),
            resolution_end=datetime(2026, 6, 2, 12, 0, 5),
            proposed_resolution=ProposedResolution(git_archive="archive"),
        ),
    )


def successful_diff_tree(*args, **kwargs):
    if args[2] == "show":
        return CompletedProcess(args=[], returncode=0, stdout="p1 p2\n", stderr="")

    if args[2] == "merge-tree":
        return CompletedProcess(args=[], returncode=1, stdout="conflicted-tree\0metadata", stderr="")

    patch = "-p" in args
    refs = args[-2:]
    flags = [arg for arg in args[4:-2] if arg != "-p"]
    output_type = "patch" if patch else "raw"
    return CompletedProcess(
        args=[],
        returncode=0,
        stdout=f"{output_type} {'+'.join(flags) or 'exact'} {refs[0]}..{refs[1]}\n".encode(),
        stderr=b"",
    )


def diff_tree_calls(calls):
    return [call.args for call in calls if call.args[2] == "diff-tree"]


def test_diff_analysis_records_patch_and_raw_diff_tree_outputs(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git_bytes") as diff_capture_git_bytes,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git.side_effect = successful_diff_tree
        diff_capture_git_bytes.side_effect = successful_diff_tree

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.conflicted_tree_oid == "conflicted-tree"
    assert record.proposed_to_actual_resolution_patch == "patch exact HEAD..actualsha\n"
    assert record.proposed_to_actual_resolution_raw == "raw exact HEAD..actualsha\n"
    assert record.conflicted_to_actual_resolution_patch == "patch exact conflicted-tree..actualsha\n"
    assert record.conflicted_to_actual_resolution_raw == "raw exact conflicted-tree..actualsha\n"
    assert record.conflicted_to_proposed_resolution_patch == "patch exact conflicted-tree..HEAD\n"
    assert record.conflicted_to_proposed_resolution_raw == "raw exact conflicted-tree..HEAD\n"
    assert (
        record.proposed_to_actual_resolution_diffs["ignore_all_space"]["ignore_blank_lines"].patch
        == "patch --ignore-all-space+--ignore-blank-lines HEAD..actualsha\n"
    )
    assert (
        record.conflicted_to_actual_resolution_diffs["ignore_space_change"]["include_blank_lines"].raw
        == "raw --ignore-space-change conflicted-tree..actualsha\n"
    )
    assert (
        record.conflicted_to_proposed_resolution_diffs["ignore_cr_at_eol"]["ignore_blank_lines"].patch
        == "patch --ignore-cr-at-eol+--ignore-blank-lines conflicted-tree..HEAD\n"
    )
    assert record.proposed_to_actual_resolution_diffs["exact"]["include_blank_lines"].exact_match is False
    assert record.error is None
    dumped = record.model_dump()
    assert "configuration" not in dumped
    assert "hook_result" not in dumped
    assert "git_archive" not in dumped
    calls = diff_tree_calls(diff_capture_git_bytes.call_args_list)
    assert len(calls) == 60
    assert calls[:4] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "-p",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-blank-lines",
            "-p",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-blank-lines",
            "HEAD",
            "actualsha",
        ),
    ]
    assert calls[16:18] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-all-space",
            "-p",
            "HEAD",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-all-space",
            "HEAD",
            "actualsha",
        ),
    ]
    assert calls[36:38] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-all-space",
            "-p",
            "conflicted-tree",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "--color=always",
            "--ignore-all-space",
            "conflicted-tree",
            "actualsha",
        ),
    ]
    assert [call.args for call in diff_capture_git.call_args_list if call.args[2] != "diff-tree"] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "show",
            "--no-patch",
            "--format=%P",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "merge-tree",
            "-z",
            "p1",
            "p2",
        ),
    ]
    assert [key for key, _ in WHITESPACE_DIFF_MODES] == list(record.proposed_to_actual_resolution_diffs.keys())
    assert [key for key, _ in BLANK_LINE_DIFF_MODES] == list(
        record.proposed_to_actual_resolution_diffs["exact"].keys()
    )


def test_diff_analysis_records_exact_match_for_empty_diff(monkeypatch):
    with patch("evaluation.analysis.diff_analysis.capture_git_bytes") as diff_capture_git_bytes:
        diff_capture_git_bytes.return_value = CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        diffs, error = DiffEvaluationAnalysis().collect_diff_matrix("/playground", "HEAD", "actualsha")

    assert error is None
    assert diffs["exact"]["include_blank_lines"].patch == ""
    assert diffs["exact"]["include_blank_lines"].raw == ""
    assert diffs["exact"]["include_blank_lines"].exact_match is True


def test_diff_analysis_records_diff_command_failure(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git_bytes") as diff_capture_git_bytes,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        diff_capture_git_bytes.return_value = CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"bad diff")

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.proposed_to_actual_resolution_patch is None
    assert record.proposed_to_actual_resolution_raw is None
    assert record.proposed_to_actual_resolution_diffs == {"exact": {}}
    assert record.error == (
        "Could not diff proposed resolution against actual resolution: "
        "Could not diff HEAD against actualsha with exact/include_blank_lines patch: bad diff"
    )


def test_diff_analysis_records_conflicted_tree_comparison_failure_with_reference_diffs(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git") as diff_capture_git,
        patch("evaluation.analysis.diff_analysis.capture_git_bytes") as diff_capture_git_bytes,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")

        def clean_merge_diff_tree(*args, **kwargs):
            if args[2] == "show":
                return CompletedProcess(args=[], returncode=0, stdout="p1 p2\n", stderr="")
            if args[2] == "merge-tree":
                return CompletedProcess(args=[], returncode=0, stdout="clean-tree\0", stderr="")
            return successful_diff_tree(*args, **kwargs)

        diff_capture_git.side_effect = clean_merge_diff_tree
        diff_capture_git_bytes.side_effect = clean_merge_diff_tree

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha == "proposed-sha"
    assert record.proposed_to_actual_resolution_patch == "patch exact HEAD..actualsha\n"
    assert record.proposed_to_actual_resolution_raw == "raw exact HEAD..actualsha\n"
    assert len(diff_tree_calls(diff_capture_git_bytes.call_args_list)) == 20
    assert record.conflicted_tree_oid is None
    assert record.error == "Actual resolution parents merge cleanly"


def test_diff_analysis_replaces_invalid_utf8_diff_bytes():
    with patch("evaluation.analysis.diff_analysis.capture_git_bytes") as diff_capture_git_bytes:
        diff_capture_git_bytes.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"diff --git a/file b/file\n+\x93\n",
            stderr=b"",
        )

        diff, error = DiffEvaluationAnalysis().diff_tree(
            "/playground",
            "HEAD",
            "actualsha",
            patch=True,
        )

    assert error is None
    assert diff == "diff --git a/file b/file\n+\ufffd\n"


def test_diff_analysis_records_missing_playgrounds(monkeypatch):
    monkeypatch.delenv("PLAYGROUNDS", raising=False)

    record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "PLAYGROUNDS environment variable is not set"


def test_diff_analysis_records_unreadable_head(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with patch("evaluation.analysis.common.capture_git") as head_capture_git:
        head_capture_git.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="bad head")

        record = DiffEvaluationAnalysis().analyse(evaluation_input())

    assert record.proposed_commit_sha is None
    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "Could not read resolved HEAD: bad head"


def test_diff_analysis_rejects_playground_name_without_merge_sha(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    record = DiffEvaluationAnalysis().analyse(evaluation_input("owner/repo.git"))

    assert record.proposed_to_actual_resolution_patch is None
    assert record.error == "Could not extract merge SHA from playground name: owner/repo.git"
