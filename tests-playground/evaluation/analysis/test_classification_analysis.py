from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.classification_analysis import (
    CLASSIFIED_STATUS,
    NOT_IMPLEMENTED_STATUS,
    ClassificationEvaluationAnalysis,
)


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


def merge_result():
    return MergeResult(
        result_tree_oid="conflicted-tree",
        conflicted_files=[],
        logical_conflicts=[
            MergeLogicalConflict(
                type=ConflictType.CONFLICT_CONTENTS,
                info="CONFLICT (content): Merge conflict in src/app.py",
                paths=["src/app.py"],
            ),
            MergeLogicalConflict(
                type=ConflictType.CONFLICT_MODIFY_DELETE,
                info="CONFLICT (modify/delete): README.md deleted in feature and modified in main",
                paths=["README.md"],
            ),
        ],
    )


def test_classification_analysis_records_per_logical_conflict(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    analysis = ClassificationEvaluationAnalysis()

    def classify_resolution(playground_path, conflicted_tree_oid, merged_ref, path):
        assert playground_path == "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"
        assert conflicted_tree_oid == "conflicted-tree"
        assert path == "src/app.py"
        if merged_ref == "HEAD":
            return ["CONTEXT_UNCHANGED", "CHUNK_CANONICAL_OURS"], None
        if merged_ref == "actualsha":
            return ["CONTEXT_CHANGED", "CHUNK_CANONICAL_THEIRS"], None
        raise AssertionError(f"Unexpected merged ref: {merged_ref}")

    with (
        patch("evaluation.analysis.classification_analysis.read_head_commit") as read_head_commit,
        patch.object(analysis, "collect_parents", return_value=(["p1", "p2"], None)),
        patch.object(analysis, "collect_merge_result", return_value=(merge_result(), None)),
        patch.object(analysis, "classify_resolution", side_effect=classify_resolution),
    ):
        read_head_commit.return_value = ("proposed-sha", None)

        record = analysis.analyse(evaluation_input())

    assert record.resolution_key == "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.conflicted_tree_oid == "conflicted-tree"
    assert record.error is None
    assert len(record.logical_conflicts) == 2
    assert record.logical_conflicts[0].logical_conflict_index == 0
    assert record.logical_conflicts[0].type == ConflictType.CONFLICT_CONTENTS
    assert record.logical_conflicts[0].status == CLASSIFIED_STATUS
    assert record.logical_conflicts[0].agent_classifications == [
        "CONTEXT_UNCHANGED",
        "CHUNK_CANONICAL_OURS",
    ]
    assert record.logical_conflicts[0].human_classifications == [
        "CONTEXT_CHANGED",
        "CHUNK_CANONICAL_THEIRS",
    ]
    assert record.logical_conflicts[1].logical_conflict_index == 1
    assert record.logical_conflicts[1].type == ConflictType.CONFLICT_MODIFY_DELETE
    assert record.logical_conflicts[1].status == NOT_IMPLEMENTED_STATUS
    assert record.logical_conflicts[1].agent_classifications is None
    assert record.logical_conflicts[1].human_classifications is None
    assert (
        record.logical_conflicts[1].error
        == "Conflict resolution classification is not implemented for CONFLICT (modify/delete)"
    )
    dumped = record.model_dump()
    assert "configuration" not in dumped
    assert "hook_result" not in dumped
    assert "git_archive" not in dumped


def test_collect_merge_result_requests_diff3_conflict_markers():
    with patch("evaluation.analysis.classification_analysis.capture_git") as capture_git:
        capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="clean-tree\0", stderr="")

        merge_result_value, error = ClassificationEvaluationAnalysis().collect_merge_result(
            "/playground",
            "left",
            "right",
        )

    assert merge_result_value is None
    assert error == "Actual resolution parents merge cleanly"
    capture_git.assert_called_once_with(
        "-C",
        "/playground",
        "-c",
        "merge.conflictStyle=diff3",
        "merge-tree",
        "-z",
        "left",
        "right",
        check=False,
    )


def test_analyze_files_runs_java_jar_and_parses_classification_array(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLICT_RESOLUTION_ANALYZER_JAR", "/tools/analyzer.jar")
    unmerged_file = tmp_path / "unmerged.txt"
    merged_file = tmp_path / "merged.txt"
    unmerged_file.write_text("<<<<<<< ours\nleft\n||||||| base\nbase\n=======\nright\n>>>>>>> theirs\n")
    merged_file.write_text("left\n")

    with patch("evaluation.analysis.classification_analysis.subprocess.run") as run:
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout='["CONTEXT_UNCHANGED","CHUNK_CANONICAL_OURS"]\n',
            stderr="",
        )

        classifications, error = ClassificationEvaluationAnalysis().analyze_files(
            unmerged_file,
            merged_file,
        )

    assert error is None
    assert classifications == ["CONTEXT_UNCHANGED", "CHUNK_CANONICAL_OURS"]
    run.assert_called_once_with(
        [
            "java",
            "-jar",
            "/tools/analyzer.jar",
            "--formatting",
            str(unmerged_file),
            str(merged_file),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_classify_resolution_writes_unmerged_and_merged_temp_files():
    analysis = ClassificationEvaluationAnalysis()
    captured_files: list[tuple[Path, Path]] = []

    def read_blob(playground_path, ref, path):
        assert playground_path == "/playground"
        assert path == "src/app.py"
        return (f"{ref} content\n".encode() + b"\x93\n", None)

    def analyze_files(unmerged_file, merged_file):
        captured_files.append((unmerged_file, merged_file))
        assert unmerged_file.read_bytes() == b"conflicted-tree content\n\x93\n"
        assert merged_file.read_bytes() == b"HEAD content\n\x93\n"
        return ["CHUNK_NONCANONICAL"], None

    with (
        patch.object(analysis, "read_blob", side_effect=read_blob),
        patch.object(analysis, "analyze_files", side_effect=analyze_files),
    ):
        classifications, error = analysis.classify_resolution(
            "/playground",
            "conflicted-tree",
            "HEAD",
            "src/app.py",
        )

    assert error is None
    assert classifications == ["CHUNK_NONCANONICAL"]
    assert len(captured_files) == 1
