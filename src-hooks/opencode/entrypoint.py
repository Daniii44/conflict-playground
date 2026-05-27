#!/usr/bin/env python3

import os
import subprocess
from pathlib import Path

from hooks_common import HookWorker, HookTask


class OpenCodeWorker(HookWorker):
    """Hook worker that lets opencode resolve a prepared merge conflict."""

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
            "commit",
            "--no-edit",
        )

    def handle_task(self, task: HookTask) -> str:
        """Run opencode in the playground directory and report the result."""
        playground_base_path = os.environ.get("PLAYGROUNDS")
        if playground_base_path is None:
            raise ValueError("PLAYGROUNDS environment variable is not set")
        playground_path = Path(playground_base_path) / task.playground

        if not playground_path.is_dir():
            return f"Error: Playground directory '{playground_path}' does not exist"

        if not self.is_merging(playground_path):
            return f"Error: Playground '{task.playground}' is not in a git merge state"


        try:
            opencode_result = subprocess.run(
                ["/root/.opencode/bin/opencode", "run", "--command", "resolve-conflicts", "--dir", str(playground_path)],
                cwd=playground_path,
            )
        except FileNotFoundError:
            return "Error: opencode executable not found"
        except Exception as e:
            return f"Error running opencode: {e}"

        if self.is_merging(playground_path):
            if self.has_unmerged_changes(playground_path):
                return (
                    f"Error: opencode exited with code {opencode_result.returncode}, "
                    "but the repository is still merging and has unmerged changes"
                )

            commit_result = self.finish_merge(playground_path)
            if commit_result.returncode != 0:
                error = commit_result.stderr.strip() or commit_result.stdout.strip()
                return (
                    "Error: opencode left the repository in a merge state without unmerged "
                    f"changes, and automatic git commit --no-edit failed: {error}"
                )

            return (
                "Error hint: opencode resolved all unmerged changes but did not commit the "
                f"merge. The hook committed it with git commit --no-edit. "
                f"opencode exit code: {opencode_result.returncode}"
            )

        if opencode_result.returncode != 0:
            return f"Error: opencode exited with code {opencode_result.returncode}"

        return "opencode completed conflict resolution"


if __name__ == '__main__':
    worker = OpenCodeWorker()
    worker.listen()
