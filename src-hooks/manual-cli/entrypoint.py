#!/usr/bin/env python3

import os
import sys
import pty
import select
import signal
import subprocess
from hooks_common import HookWorker, HookTask


class MyHookWorker(HookWorker):
    """Example hook worker implementation."""

    def handle_task(self, task: HookTask) -> str:
        """Spawn an interactive zsh session in the playground directory."""
        playground_base_path = os.environ.get("PLAYGROUNDS")
        if playground_base_path is None:
            raise ValueError("PLAYGROUNDS environment variable is not set")
        playground_path = playground_base_path + "/" + task.playground
        
        # Verify the playground directory exists
        if not os.path.isdir(playground_path):
            pass
            # return f"Error: Playground directory '{playground_path}' does not exist"
        
        print(f"Spawning interactive zsh session in: {playground_path}")
        
        # Spawn an interactive zsh shell in the playground directory
        # Use os.setsid to create a new session with its own process group
        # This allows proper signal handling and TTY control
        try:
            # Start zsh with login shell (-l) for full environment setup
            # The process inherits stdin/stdout/stderr from the parent
            # When run in Docker with -it, these are connected to the TTY
            process = subprocess.Popen(
                ['zsh', '-l'],
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                cwd=playground_path,
                start_new_session=True
            )
            
            # Wait for the shell to exit
            # This blocks until the user exits the interactive session
            exit_code = process.wait()
            
            return f"Interactive session in '{playground_path}' completed with exit code {exit_code}"
            
        except Exception as e:
            return f"Error spawning interactive session: {str(e)}"


if __name__ == '__main__':
    worker = MyHookWorker()
    worker.listen()