from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.modifydelete_analysis import (
    CANONICAL_BASE,
    CANONICAL_DELETE,
    CANONICAL_KEEP,
    NONCANONICAL,
    ModifyDeleteEvaluationAnalysis,
)


class FakeRedis:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self

    def get(self, key):
        assert key == "info:conflict:modifydelete:owner/repo.git:actualsha"
        return self.payload


def evaluation_input():
    return EvaluationInput(
        resolution_key="resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z",
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha",
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


def test_modifydelete_evaluation_classifies_each_resolution_from_stored_stage_oids(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    payload = {
        "repo": "owner/repo.git",
        "merge_commit_oid": "actualsha",
        "conflicted_tree_oid": "conflicted-tree",
        "conflicts": [
            {"logical_conflict_index": 0, "path": "base.txt", "base_oid": "base", "ours_oid": "ours"},
            {"logical_conflict_index": 1, "path": "keep.txt", "base_oid": "base", "theirs_oid": "theirs"},
            {"logical_conflict_index": 2, "path": "delete.txt", "base_oid": "base", "ours_oid": "ours"},
            {"logical_conflict_index": 3, "path": "changed.txt", "base_oid": "base", "ours_oid": "ours"},
        ],
    }
    analysis = ModifyDeleteEvaluationAnalysis(redis_client=FakeRedis(payload))

    def tree_oid_for_path(playground_path, ref, path):
        assert playground_path == "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha"
        oids = {
            ("HEAD", "base.txt"): "base",
            ("actualsha", "base.txt"): "ours",
            ("HEAD", "keep.txt"): "theirs",
            ("actualsha", "keep.txt"): "theirs",
            ("HEAD", "delete.txt"): None,
            ("actualsha", "delete.txt"): "ours",
            ("HEAD", "changed.txt"): "new",
            ("actualsha", "changed.txt"): "newer",
        }
        return oids[(ref, path)], None

    with (
        patch("evaluation.analysis.modifydelete_analysis.read_head_commit", return_value=("proposed-sha", None)),
        patch.object(analysis, "tree_oid_for_path", side_effect=tree_oid_for_path),
    ):
        record = analysis.analyse(evaluation_input())

    assert record.error is None
    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert [item.agent_classification for item in record.path_evaluations] == [
        CANONICAL_BASE,
        CANONICAL_KEEP,
        CANONICAL_DELETE,
        NONCANONICAL,
    ]
    assert [item.human_classification for item in record.path_evaluations] == [
        CANONICAL_KEEP,
        CANONICAL_KEEP,
        CANONICAL_KEEP,
        NONCANONICAL,
    ]


def test_tree_oid_for_path_uses_ls_tree_and_treats_missing_path_as_delete():
    analysis = ModifyDeleteEvaluationAnalysis(redis_client=object())
    with patch("evaluation.analysis.modifydelete_analysis.capture_git") as capture_git:
        capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="100644 blob blob-oid\tfile.txt\0", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ]

        assert analysis.tree_oid_for_path("/playground", "HEAD", "file.txt") == ("blob-oid", None)
        assert analysis.tree_oid_for_path("/playground", "HEAD", "missing.txt") == (None, None)

    assert [call.args for call in capture_git.call_args_list] == [
        ("-C", "/playground", "ls-tree", "-z", "HEAD", "--", "file.txt"),
        ("-C", "/playground", "ls-tree", "-z", "HEAD", "--", "missing.txt"),
    ]
