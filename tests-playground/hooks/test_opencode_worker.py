import importlib.util
import subprocess
import sys
from pathlib import Path


def load_opencode_module():
    repo_root = Path(__file__).resolve().parents[2]
    hooks_path = repo_root / "src-hooks"
    sys.path.insert(0, str(hooks_path))
    try:
        spec = importlib.util.spec_from_file_location(
            "opencode_entrypoint",
            hooks_path / "opencode" / "entrypoint.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(hooks_path))


def test_run_opencode_json_returns_stderr_for_nonzero_exit(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()

    def fake_run(args, **kwargs):
        assert kwargs["stderr"] == subprocess.PIPE
        return subprocess.CompletedProcess(
            args,
            1,
            stdout=None,
            stderr="Configuration is invalid at .opencode/opencode.json\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result, error = worker.run_opencode_json(tmp_path, "session", "list")

    assert result is None
    assert "Configuration is invalid" in error


def test_handle_task_returns_invalid_config_error(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "example-project-abc123"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(worker, "is_merging", lambda path: True)
    monkeypatch.setattr(worker, "has_unmerged_changes", lambda path: True)
    monkeypatch.setattr(worker, "export_latest_session", lambda path: {"error": "No session"})

    def fake_run(args, **kwargs):
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="Configuration is invalid at .opencode/opencode.json\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = worker.handle_task(module.HookTask(id="00000000-0000-0000-0000-000000000001", playground="example-project-abc123"))

    assert result["opencode_exit_code"] == 1
    assert result["message"].startswith("Error: opencode exited with code 1")
    assert "Configuration is invalid" in result["message"]
