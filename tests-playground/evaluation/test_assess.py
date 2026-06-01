from subprocess import CompletedProcess
from unittest.mock import patch

from evaluation.assess import collect_proposed_resolution


def test_collect_proposed_resolution_records_colored_diff(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with patch("evaluation.assess.capture_git") as capture_git:
        capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="\x1b[31m-diff\x1b[m\n", stderr=""),
        ]

        proposed_resolution = collect_proposed_resolution("owner/repo.git-actualsha")

    assert proposed_resolution.commit_sha == "proposed-sha"
    assert proposed_resolution.actual_resolution_sha == "actualsha"
    assert proposed_resolution.diff_to_actual_resolution == "\x1b[31m-diff\x1b[m\n"
    assert proposed_resolution.error is None
    capture_git.assert_any_call(
        "-C",
        "/playgrounds/owner/repo.git-actualsha",
        "diff",
        "--color=always",
        "HEAD",
        "actualsha",
        check=False,
    )
