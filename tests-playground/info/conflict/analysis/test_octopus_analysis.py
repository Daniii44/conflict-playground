from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.octopus_analysis import InfoConflictOctopus, OctopusAnalysis


def merge_result() -> MergeResult:
    return MergeResult(
        result_tree_oid="tree",
        conflicted_files=[],
        logical_conflicts=[
            MergeLogicalConflict(
                type=ConflictType.CONFLICT_CONTENTS,
                info="Merge conflict in README.md",
                paths=["README.md"],
            )
        ],
    )


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        git_dir="/repos/example.git",
        git_repo_name="owner/repo.git",
        merge_commit_oid="merge-sha",
    )


def test_analyse_skips_non_octopus_merges(monkeypatch):
    analysis = OctopusAnalysis("octopus")
    merge_attempt_called = False

    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2"])

    def fake_try_octopus_merge(_git_dir, _parents):
        nonlocal merge_attempt_called
        merge_attempt_called = True
        return True, None

    monkeypatch.setattr(analysis, "try_octopus_merge", fake_try_octopus_merge)

    assert analysis.analyse(analysis_input()) is None
    assert merge_attempt_called is False


def test_analyse_records_clean_octopus_merge_without_pairwise_search(monkeypatch):
    analysis = OctopusAnalysis("octopus")
    input_ = analysis_input()
    pairwise_called = False

    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2", "p3"])

    def fake_try_octopus_merge(git_dir, parents):
        assert git_dir == input_.git_dir
        assert parents == ["p1", "p2", "p3"]
        return True, None

    def fake_collect_pairwise_conflicts(_git_dir, _parents):
        nonlocal pairwise_called
        pairwise_called = True
        return []

    monkeypatch.setattr(analysis, "try_octopus_merge", fake_try_octopus_merge)
    monkeypatch.setattr(analysis, "collect_pairwise_conflicts", fake_collect_pairwise_conflicts)

    result = analysis.analyse(input_)

    assert pairwise_called is False
    assert result is not None
    returned_input, conflict = result
    assert returned_input == input_
    assert isinstance(conflict, InfoConflictOctopus)
    assert conflict.parent_count == 3
    assert conflict.parent_oids == ["p1", "p2", "p3"]
    assert conflict.octopus_merge_clean is True
    assert conflict.octopus_merge_error is None
    assert conflict.pairwise_conflicts == []


def test_analyse_records_pairwise_conflicts_when_octopus_merge_fails(monkeypatch):
    analysis = OctopusAnalysis("octopus")
    input_ = analysis_input()
    expected_merge_result = merge_result()
    core_calls = []

    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2", "p3"])
    monkeypatch.setattr(
        analysis,
        "try_octopus_merge",
        lambda _git_dir, _parents: (False, "Merge with strategy octopus failed."),
    )

    def fake_collect_bare_merge_result(git_dir, parent_a_oid, parent_b_oid):
        core_calls.append((git_dir, parent_a_oid, parent_b_oid))
        if (parent_a_oid, parent_b_oid) == ("p1", "p3"):
            return expected_merge_result
        return None

    monkeypatch.setattr(
        analysis._core_analysis,
        "collect_bare_merge_result",
        fake_collect_bare_merge_result,
    )

    result = analysis.analyse(input_)

    assert core_calls == [
        (input_.git_dir, "p1", "p2"),
        (input_.git_dir, "p1", "p3"),
        (input_.git_dir, "p2", "p3"),
    ]
    assert result is not None
    returned_input, conflict = result
    assert returned_input == input_
    assert conflict.octopus_merge_clean is False
    assert conflict.octopus_merge_error == "Merge with strategy octopus failed."
    assert len(conflict.pairwise_conflicts) == 1
    assert conflict.pairwise_conflicts[0].parent_a_index == 1
    assert conflict.pairwise_conflicts[0].parent_a_oid == "p1"
    assert conflict.pairwise_conflicts[0].parent_b_index == 3
    assert conflict.pairwise_conflicts[0].parent_b_oid == "p3"
    assert conflict.pairwise_conflicts[0].merge_result == expected_merge_result
