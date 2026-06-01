import subprocess
from pathlib import Path

from common.merge_tree import MergeResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.core_analysis import CoreAnalysis, InfoConflictCore
from playground.setup import playground_name


def completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def merge_result() -> MergeResult:
    return MergeResult(
        result_tree_oid="tree",
        conflicted_files=[],
        logical_conflicts=[],
    )


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        git_dir="/repos/example.git",
        git_repo_name="owner/repo.git",
        merge_commit_oid="merge-sha",
    )


def test_state_has_submodules_returns_false_for_normal_entries(monkeypatch):
    calls = []

    def fake_capture_git(*args, check=True, cwd=None):
        calls.append(args)
        return completed_process(
            stdout=(
                "100644 blob abc123\tREADME.md\0"
                "040000 tree def456\tsrc\0"
            )
        )

    monkeypatch.setattr(
        "info.conflict.analysis.core_analysis.capture_git",
        fake_capture_git,
    )

    assert CoreAnalysis("core").state_has_submodules(analysis_input(), ["p1", "p2"]) is False
    assert len(calls) == 2


def test_state_has_submodules_returns_true_for_gitlink(monkeypatch):
    outputs = iter([
        completed_process(stdout="100644 blob abc123\tREADME.md\0"),
        completed_process(stdout="160000 commit abc123\tdeps/lib\0"),
    ])

    monkeypatch.setattr(
        "info.conflict.analysis.core_analysis.capture_git",
        lambda *args, check=True, cwd=None: next(outputs),
    )

    assert CoreAnalysis("core").state_has_submodules(analysis_input(), ["p1", "p2"]) is True


def test_analyse_uses_bare_merge_tree_without_submodules(monkeypatch):
    analysis = CoreAnalysis("core")
    expected_merge_result = merge_result()
    setup_called = False

    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2"])
    monkeypatch.setattr(analysis, "state_has_submodules", lambda _analysis_input, _parents: False)

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


def test_analyse_uses_playground_merge_tree_with_submodules(monkeypatch, tmp_path):
    analysis = CoreAnalysis("core")
    input_ = analysis_input()
    expected_merge_result = merge_result()
    setup_calls = []
    collect_calls = []
    cleanup_calls = []

    monkeypatch.setenv("PLAYGROUNDS", str(tmp_path))
    monkeypatch.setattr(analysis, "collect_parents", lambda _analysis_input: ["p1", "p2"])
    monkeypatch.setattr(analysis, "state_has_submodules", lambda _analysis_input, _parents: True)

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
    monkeypatch.setattr(
        analysis,
        "collect_playground_merge_result",
        fake_collect_playground_merge_result,
    )
    monkeypatch.setattr("info.conflict.analysis.core_analysis.shutil.rmtree", fake_rmtree)

    result = analysis.analyse(input_)

    expected_path = tmp_path / playground_name(input_.git_repo_name, input_.merge_commit_oid)
    assert setup_calls == [(input_.git_repo_name, input_.merge_commit_oid)]
    assert collect_calls == [expected_path]
    assert cleanup_calls == [(expected_path, True)]
    assert result is not None
    returned_input, conflict = result
    assert returned_input == input_
    assert isinstance(conflict, InfoConflictCore)
    assert conflict.merge_result == expected_merge_result
