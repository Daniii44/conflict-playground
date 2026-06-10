#!/usr/bin/env python3

import json
import os
import subprocess
from pathlib import Path
import tempfile
from typing import Any

from hooks_common import HookWorker, HookTask


OPENCODE_ERROR_EXCERPT_LIMIT = 4000


def command_error_excerpt(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if part and part.strip()
    )
    if len(output) <= OPENCODE_ERROR_EXCERPT_LIMIT:
        return output
    return output[:OPENCODE_ERROR_EXCERPT_LIMIT].rstrip() + "\n... truncated"


class OpenCodeWorker(HookWorker):
    """Hook worker that lets opencode resolve a prepared merge conflict."""

    opencode_executable = "/root/.opencode/bin/opencode"

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

    def run_opencode_json(self, playground_path: Path, *args: str) -> tuple[Any | None, str | None]:
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
            return {"error": list_error}

        session_id = self.latest_session_id(session_list)
        if session_id is None:
            return {"error": "No latest opencode session ID found", "session_list": session_list}

        session_export, export_error = self.run_opencode_json(playground_path, "export", session_id)
        if export_error is not None:
            return {"id": session_id, "error": export_error}

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
        playground_base_path = os.environ.get("PLAYGROUNDS")
        if playground_base_path is None:
            raise ValueError("PLAYGROUNDS environment variable is not set")
        playground_path = Path(playground_base_path) / task.playground

        if not playground_path.is_dir():
            return self.result(f"Error: Playground directory '{playground_path}' does not exist")

        if not self.is_merging(playground_path):
            return self.result(f"Error: Playground '{task.playground}' is not in a git merge state")

        try:
            opencode_result = subprocess.run(
                [
                    self.opencode_executable,
                    "run",
                    "--command",
                    "resolve-conflicts",
                    "--dir",
                    str(playground_path),
                ],
                cwd=playground_path,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return self.result("Error: opencode executable not found")
        except Exception as e:
            return self.result(f"Error running opencode: {e}")

        session_export = self.export_latest_session(playground_path)
        opencode_error = command_error_excerpt(opencode_result)
        opencode_error_suffix = f": {opencode_error}" if opencode_error else ""

        if self.is_merging(playground_path):
            if self.has_unmerged_changes(playground_path):
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
                return self.result(
                    "Error: opencode left the repository in a merge state without unmerged "
                    f"changes, and automatic git commit --no-edit failed: {error}",
                    opencode_exit_code=opencode_result.returncode,
                    session_export=session_export,
                )

            return self.result(
                "Error hint: opencode resolved all unmerged changes but did not commit the "
                f"merge. The hook committed it with git commit --no-edit. "
                f"opencode exit code: {opencode_result.returncode}{opencode_error_suffix}",
                opencode_exit_code=opencode_result.returncode,
                session_export=session_export,
            )

        if opencode_result.returncode != 0:
            return self.result(
                f"Error: opencode exited with code {opencode_result.returncode}{opencode_error_suffix}",
                opencode_exit_code=opencode_result.returncode,
                session_export=session_export,
            )

        return self.result(
            "opencode completed conflict resolution",
            opencode_exit_code=opencode_result.returncode,
            session_export=session_export,
        )


if __name__ == '__main__':
    worker = OpenCodeWorker()
    worker.listen()
