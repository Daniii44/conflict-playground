#!/usr/bin/env python3

import json
import os
import subprocess
import threading
import time
from pathlib import Path
import tempfile
from typing import Any

from hooks_common import HookWorker, HookTask


OPENCODE_ERROR_EXCERPT_LIMIT = 4000
OPENCODE_RUN_TIMEOUT_SECONDS = 15 * 60
DEFAULT_OPENCODE_MODEL = "ollama/qwen3-coder-next:latest"
SUPPORTED_OPENCODE_MODELS = {
    "qwen3-coder-next:latest": "ollama/qwen3-coder-next:latest",
    "ollama/qwen3-coder-next:latest": "ollama/qwen3-coder-next:latest",
    "qwen3.6:35b-mlx": "ollama/qwen3.6:35b-mlx",
    "ollama/qwen3.6:35b-mlx": "ollama/qwen3.6:35b-mlx",
}


def command_error_excerpt(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if part and part.strip()
    )
    if len(output) <= OPENCODE_ERROR_EXCERPT_LIMIT:
        return output
    return output[:OPENCODE_ERROR_EXCERPT_LIMIT].rstrip() + "\n... truncated"


def timeout_error_excerpt(error: subprocess.TimeoutExpired) -> str:
    def output_text(part: str | bytes | None) -> str:
        if isinstance(part, bytes):
            return part.decode(errors="replace")
        return part or ""

    output = "\n".join(
        text.strip()
        for part in (error.stderr, error.stdout)
        if (text := output_text(part)).strip()
    )
    if len(output) <= OPENCODE_ERROR_EXCERPT_LIMIT:
        return output
    return output[:OPENCODE_ERROR_EXCERPT_LIMIT].rstrip() + "\n... truncated"


class OpenCodeWorker(HookWorker):
    """Hook worker that lets opencode resolve a prepared merge conflict."""

    opencode_executable = "/root/.opencode/bin/opencode"

    def log(self, message: str) -> None:
        super().log(f"[opencode] {message}")

    def git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_ASKPASS": "false",
                "GIT_TERMINAL_PROMPT": "0",
                "SSH_ASKPASS": "false",
                "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes",
            }
        )
        return env

    def run_git(self, playground_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=playground_path,
            text=True,
            capture_output=True,
            env=self.git_env(),
        )

    def stream_command_to_stdout(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout: int,
        label: str,
    ) -> subprocess.CompletedProcess[str]:
        self.log(
            f"starting {label} command cwd={cwd} timeout={timeout}s command={' '.join(command)}"
        )
        start = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.log(f"{label} pid={process.pid}")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def forward_output(
            stream: Any | None,
            chunks: list[str],
            stream_name: str,
        ) -> None:
            if stream is None:
                return
            try:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    print(f"[opencode/{stream_name}] {line}", end="", flush=True)
            finally:
                stream.close()

        stdout_thread = threading.Thread(
            target=forward_output,
            args=(process.stdout, stdout_chunks, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=forward_output,
            args=(process.stderr, stderr_chunks, "stderr"),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            self.log(
                f"{label} timed out after {timeout}s; terminating pid={process.pid}"
            )
            process.kill()
            process.wait()
            stdout_thread.join()
            stderr_thread.join()
            duration = time.monotonic() - start
            stdout_text = "".join(stdout_chunks)
            stderr_text = "".join(stderr_chunks)
            self.log(
                f"{label} collected stdout_chars={len(stdout_text)} stderr_chars={len(stderr_text)} "
                f"before timeout after {duration:.2f}s"
            )
            raise subprocess.TimeoutExpired(
                error.cmd,
                error.timeout,
                output=stdout_text,
                stderr=stderr_text,
            ) from None

        stdout_thread.join()
        stderr_thread.join()
        duration = time.monotonic() - start
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        self.log(
            f"{label} exited rc={returncode} after {duration:.2f}s "
            f"stdout_chars={len(stdout_text)} stderr_chars={len(stderr_text)}"
        )
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )

    def is_merging(self, playground_path: Path) -> bool:
        result = self.run_git(playground_path, "rev-parse", "-q", "--verify", "MERGE_HEAD")
        return result.returncode == 0

    def has_unmerged_changes(self, playground_path: Path) -> bool:
        result = self.run_git(playground_path, "ls-files", "-u")
        return result.returncode == 0 and bool(result.stdout.strip())

    def finish_merge(self, playground_path: Path) -> subprocess.CompletedProcess[str]:
        return self.run_git(
            playground_path,
            "-c",
            "user.name=Conflict Playground",
            "-c",
            "user.email=conflict-playground@example.invalid",
            "commit",
            "--no-edit",
        )

    def selected_model(self) -> str:
        configured_model = os.environ.get("OPENCODE_MODEL", "").strip()
        if not configured_model:
            return DEFAULT_OPENCODE_MODEL

        selected_model = SUPPORTED_OPENCODE_MODELS.get(configured_model)
        if selected_model is None:
            supported_models = ", ".join(sorted({model for model in SUPPORTED_OPENCODE_MODELS if not model.startswith("ollama/")}))
            raise ValueError(
                f"Unsupported OPENCODE_MODEL {configured_model!r}. Supported models: {supported_models}"
            )
        return selected_model

    def run_opencode_json(self, playground_path: Path, *args: str) -> tuple[Any | None, str | None]:
        self.log(
            f"running JSON command in {playground_path}: "
            f"{self.opencode_executable} {' '.join(args)}"
        )
        with tempfile.NamedTemporaryFile(mode='w+') as tf:
            result = subprocess.run(
                [self.opencode_executable, *args],
                cwd=playground_path,
                text=True,
                stdout=tf,
                stderr=subprocess.PIPE,
            )
            tf.seek(0)
            session_data = tf.read()
        self.log(
            f"JSON command {' '.join(args)} exited rc={result.returncode} "
            f"stdout_chars={len(session_data)} stderr_chars={len(result.stderr or '')}"
        )
        if result.returncode != 0:
            error = (result.stderr or "").strip() or session_data.strip()
            return None, error or f"opencode {' '.join(args)} exited with code {result.returncode}"

        try:
            return json.loads(session_data), None
        except json.JSONDecodeError as e:
            return None, f"opencode {' '.join(args)} returned invalid JSON: {e}"

    def latest_session_id(self, session_list: Any) -> str | None:
        if isinstance(session_list, list) and session_list:
            session = session_list[0]
        elif isinstance(session_list, dict):
            sessions = session_list.get("sessions")
            if isinstance(sessions, list) and sessions:
                session = sessions[0]
            else:
                session = session_list
        else:
            return None

        if not isinstance(session, dict):
            return None

        for key in ("id", "sessionID", "sessionId", "session_id"):
            value = session.get(key)
            if isinstance(value, str) and value:
                return value

        return None

    def export_latest_session(self, playground_path: Path) -> dict[str, Any]:
        self.log(f"exporting latest opencode session for {playground_path}")
        session_list, list_error = self.run_opencode_json(
            playground_path,
            "session",
            "list",
            "--max-count",
            "1",
            "--format",
            "json",
        )
        if list_error is not None:
            self.log(f"failed to list opencode sessions: {list_error}")
            return {"error": list_error}

        session_id = self.latest_session_id(session_list)
        if session_id is None:
            self.log("opencode session list did not include a usable session id")
            return {"error": "No latest opencode session ID found", "session_list": session_list}

        self.log(f"found latest opencode session id={session_id}")
        session_export, export_error = self.run_opencode_json(playground_path, "export", session_id)
        if export_error is not None:
            self.log(f"failed to export opencode session id={session_id}: {export_error}")
            return {"id": session_id, "error": export_error}

        self.log(f"exported opencode session id={session_id}")
        return {"id": session_id, "data": session_export}

    def result(
        self,
        message: str,
        *,
        opencode_exit_code: int | None = None,
        session_export: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message}
        if opencode_exit_code is not None:
            payload["opencode_exit_code"] = opencode_exit_code
        if session_export is not None:
            payload["opencode_session_export"] = session_export
        return payload

    def handle_task(self, task: HookTask) -> dict[str, Any]:
        """Run opencode in the playground directory and report the result."""
        self.log(f"handling task id={task.id} playground={task.playground}")
        playground_base_path = os.environ.get("PLAYGROUNDS")
        if playground_base_path is None:
            raise ValueError("PLAYGROUNDS environment variable is not set")
        playground_path = Path(playground_base_path) / task.playground
        self.log(f"resolved playground path to {playground_path}")

        if not playground_path.is_dir():
            self.log("playground directory is missing")
            return self.result(f"Error: Playground directory '{playground_path}' does not exist")

        if not self.is_merging(playground_path):
            self.log("playground is not currently in a git merge state")
            return self.result(f"Error: Playground '{task.playground}' is not in a git merge state")

        try:
            selected_model = self.selected_model()
        except ValueError as error:
            self.log(f"failed to select model: {error}")
            return self.result(f"Error: {error}")
        self.log(f"selected model {selected_model}")

        try:
            opencode_result = self.stream_command_to_stdout(
                [
                    self.opencode_executable,
                    "run",
                    "--model",
                    selected_model,
                    "--command",
                    "resolve-conflicts",
                    "--dir",
                    str(playground_path),
                ],
                cwd=playground_path,
                timeout=OPENCODE_RUN_TIMEOUT_SECONDS,
                label="opencode run",
            )
        except subprocess.TimeoutExpired as e:
            opencode_error = timeout_error_excerpt(e)
            opencode_error_suffix = f": {opencode_error}" if opencode_error else ""
            self.log(
                f"opencode timed out for task id={task.id} playground={task.playground} "
                f"output_excerpt={opencode_error!r}"
            )
            return self.result(
                "Error: opencode timed out after "
                f"{OPENCODE_RUN_TIMEOUT_SECONDS // 60} minutes{opencode_error_suffix}",
                session_export=self.export_latest_session(playground_path),
            )
        except FileNotFoundError:
            self.log("opencode executable not found")
            return self.result("Error: opencode executable not found")
        except Exception as e:
            self.log(f"unexpected opencode execution error: {type(e).__name__}: {e}")
            return self.result(f"Error running opencode: {e}")

        session_export = self.export_latest_session(playground_path)
        opencode_error = command_error_excerpt(opencode_result)
        opencode_error_suffix = f": {opencode_error}" if opencode_error else ""
        self.log(
            f"opencode finished rc={opencode_result.returncode} "
            f"merge_state_after_run={self.is_merging(playground_path)} "
            f"session_export_keys={sorted(session_export.keys())}"
        )

        if self.is_merging(playground_path):
            if self.has_unmerged_changes(playground_path):
                self.log("repository is still merging and still has unmerged changes")
                return self.result(
                    f"Error: opencode exited with code {opencode_result.returncode}, "
                    "but the repository is still merging and has unmerged changes"
                    f"{opencode_error_suffix}",
                    opencode_exit_code=opencode_result.returncode,
                    session_export=session_export,
                )

            commit_result = self.finish_merge(playground_path)
            if commit_result.returncode != 0:
                error = commit_result.stderr.strip() or commit_result.stdout.strip()
                if opencode_error:
                    error = f"{error}; opencode output: {opencode_error}" if error else opencode_error
                self.log(f"automatic merge commit failed: {error}")
                return self.result(
                    "Error: opencode left the repository in a merge state without unmerged "
                    f"changes, and automatic git commit --no-edit failed: {error}",
                    opencode_exit_code=opencode_result.returncode,
                    session_export=session_export,
                )

            self.log("automatic merge commit completed after opencode left MERGE_HEAD in place")
            return self.result(
                "Error hint: opencode resolved all unmerged changes but did not commit the "
                f"merge. The hook committed it with git commit --no-edit. "
                f"opencode exit code: {opencode_result.returncode}{opencode_error_suffix}",
                opencode_exit_code=opencode_result.returncode,
                session_export=session_export,
            )

        if opencode_result.returncode != 0:
            self.log(f"opencode exited non-zero with excerpt={opencode_error!r}")
            return self.result(
                f"Error: opencode exited with code {opencode_result.returncode}{opencode_error_suffix}",
                opencode_exit_code=opencode_result.returncode,
                session_export=session_export,
            )

        self.log("opencode completed successfully and repository is no longer merging")
        return self.result(
            "opencode completed conflict resolution",
            opencode_exit_code=opencode_result.returncode,
            session_export=session_export,
        )


if __name__ == '__main__':
    worker = OpenCodeWorker()
    worker.listen()
