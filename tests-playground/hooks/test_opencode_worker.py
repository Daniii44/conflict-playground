import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


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

    def fake_stream(command, **kwargs):
        assert command[:4] == [
            worker.opencode_executable,
            "run",
            "--model",
            module.DEFAULT_OPENCODE_MODEL,
        ]
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Configuration is invalid at .opencode/opencode.json\n",
        )

    monkeypatch.setattr(worker, "stream_command_to_stdout", fake_stream)

    result = worker.handle_task(module.HookTask(id="00000000-0000-0000-0000-000000000001", playground="example-project-abc123"))

    assert result["opencode_exit_code"] == 1
    assert result["message"].startswith("Error: opencode exited with code 1")
    assert "Configuration is invalid" in result["message"]


def test_handle_task_returns_timeout_as_normal_error(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "example-project-abc123"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))

    monkeypatch.setattr(worker, "is_merging", lambda path: True)
    monkeypatch.setattr(worker, "export_latest_session", lambda path: {"error": "No session"})

    def fake_stream(command, **kwargs):
        assert kwargs["timeout"] == module.OPENCODE_RUN_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="still running\n", stderr="")

    monkeypatch.setattr(worker, "stream_command_to_stdout", fake_stream)

    result = worker.handle_task(module.HookTask(id="00000000-0000-0000-0000-000000000001", playground="example-project-abc123"))

    assert result["message"].startswith("Error: opencode timed out after 15 minutes")
    assert "still running" in result["message"]
    assert result["opencode_session_export"] == {"error": "No session"}


def test_selected_model_accepts_second_supported_model(monkeypatch):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    monkeypatch.setenv("OPENCODE_MODEL", "qwen3.6:35b-mlx")

    selected_model = worker.selected_model()
    assert selected_model == "ollama/qwen3.6:35b-mlx"


def test_handle_task_returns_error_for_unsupported_model(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "example-project-abc123"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))
    monkeypatch.setenv("OPENCODE_MODEL", "bad-model")
    monkeypatch.setattr(worker, "is_merging", lambda path: True)

    result = worker.handle_task(
        module.HookTask(id="00000000-0000-0000-0000-000000000001", playground="example-project-abc123")
    )

    assert result["message"].startswith("Error: Unsupported OPENCODE_MODEL 'bad-model'")
    assert "qwen3-coder-next:latest" in result["message"]
    assert "qwen3.6:35b-mlx" in result["message"]


def test_handle_task_passes_selected_model_to_opencode(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    playgrounds = tmp_path / "playgrounds"
    playground = playgrounds / "example-project-abc123"
    playground.mkdir(parents=True)
    monkeypatch.setenv("PLAYGROUNDS", str(playgrounds))
    monkeypatch.setenv("OPENCODE_MODEL", "qwen3.6:35b-mlx")

    merge_states = iter([True, False])
    monkeypatch.setattr(worker, "is_merging", lambda path: next(merge_states))
    monkeypatch.setattr(worker, "export_latest_session", lambda path: {"id": "session-1", "data": {}})

    def fake_stream(command, **kwargs):
        assert command[:4] == [
            worker.opencode_executable,
            "run",
            "--model",
            "ollama/qwen3.6:35b-mlx",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(worker, "stream_command_to_stdout", fake_stream)

    result = worker.handle_task(
        module.HookTask(id="00000000-0000-0000-0000-000000000001", playground="example-project-abc123")
    )

    assert result["message"] == "opencode completed conflict resolution"
    assert result["opencode_exit_code"] == 0


def test_stream_command_to_stdout_prints_and_captures_child_output(monkeypatch, tmp_path):
    module = load_opencode_module()
    worker = module.OpenCodeWorker()
    stdout = io.StringIO()

    with patch.object(sys, "stdout", stdout):
        result = worker.stream_command_to_stdout(
            [
                "python3",
                "-c",
                "import sys; print('hello'); print('oops', file=sys.stderr)",
            ],
            cwd=tmp_path,
            timeout=5,
            label="test command",
        )

    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == "oops\n"
    output = stdout.getvalue()
    assert "[opencode/stdout] hello" in output
    assert "[opencode/stderr] oops" in output
