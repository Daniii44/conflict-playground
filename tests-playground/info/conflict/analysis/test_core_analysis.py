from pathlib import Path

from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.core_analysis import CoreAnalysis, InfoConflictCore
from playground.setup import playground_name


def merge_result(logical_conflicts: list[MergeLogicalConflict] | None = None) -> MergeResult:
    return MergeResult(
        result_tree_oid="tree",
        conflicted_files=[],
        logical_conflicts=logical_conflicts or [],
    )


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        git_dir="/repos/example.git",
        git_repo_name="owner/repo.git",
        merge_commit_oid="merge-sha",
    )


def submodule_not_initialized_conflict() -> MergeLogicalConflict:
    return MergeLogicalConflict(
        type=ConflictType.CONFLICT_SUBMODULE_NOT_INITIALIZED,
        info="Failed to merge submodule deps/lib (not checked out)",
        paths=["deps/lib"],
    )


def test_analyse_uses_bare_merge_tree_without_uninitialized_submodule_conflict(monkeypatch):
    analysis = CoreAnalysis("core")
    expected_merge_result = merge_result()
    setup_called = False

    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2"])

    def fake_collect_bare_merge_result(git_dir, main_oid, feature_oid):
        assert git_dir == "/repos/example.git"
        assert main_oid == "p1"
        assert feature_oid == "p2"
        return expected_merge_result

    def fake_setup_playground(repo, merge_sha):
        nonlocal setup_called
        setup_called = True

    monkeypatch.setattr(analysis, "collect_bare_merge_result", fake_collect_bare_merge_result)
    monkeypatch.setattr(
        "info.conflict.analysis.core_analysis.setup_playground",
        fake_setup_playground,
    )

    result = analysis.analyse(analysis_input())

    assert setup_called is False
    assert result is not None
    returned_input, conflict = result
    assert returned_input == analysis_input()
    assert isinstance(conflict, InfoConflictCore)
    assert conflict.merge_result == expected_merge_result


def test_analyse_uses_playground_merge_tree_for_uninitialized_submodule_conflict(monkeypatch, tmp_path):
    analysis = CoreAnalysis("core")
    input_ = analysis_input()
    bare_merge_result = merge_result([submodule_not_initialized_conflict()])
    expected_merge_result = merge_result()
    setup_calls = []
    bare_calls = []
    collect_calls = []
    cleanup_calls = []

    monkeypatch.setenv("PLAYGROUNDS", str(tmp_path))
    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2"])

    def fake_collect_bare_merge_result(git_dir, main_oid, feature_oid):
        bare_calls.append((git_dir, main_oid, feature_oid))
        return bare_merge_result

    def fake_setup_playground(repo, merge_sha):
        setup_calls.append((repo, merge_sha))

    def fake_collect_playground_merge_result(playground_path: Path):
        collect_calls.append(playground_path)
        return expected_merge_result

    def fake_rmtree(path, ignore_errors=False):
        cleanup_calls.append((path, ignore_errors))

    monkeypatch.setattr(
        "info.conflict.analysis.core_analysis.setup_playground",
        fake_setup_playground,
    )
    monkeypatch.setattr(analysis, "collect_bare_merge_result", fake_collect_bare_merge_result)
    monkeypatch.setattr(
        analysis,
        "collect_playground_merge_result",
        fake_collect_playground_merge_result,
    )
    monkeypatch.setattr("info.conflict.analysis.core_analysis.shutil.rmtree", fake_rmtree)

    result = analysis.analyse(input_)

    expected_path = tmp_path / playground_name(input_.git_repo_name, input_.merge_commit_oid)
    assert bare_calls == [(input_.git_dir, "p1", "p2")]
    assert setup_calls == [(input_.git_repo_name, input_.merge_commit_oid)]
    assert collect_calls == [expected_path]
    assert cleanup_calls == [(expected_path, True)]
    assert result is not None
    returned_input, conflict = result
    assert returned_input == input_
    assert isinstance(conflict, InfoConflictCore)
    assert conflict.merge_result == expected_merge_result
