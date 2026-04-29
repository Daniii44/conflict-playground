#!/usr/bin/env python3

from hooks_common import HookWorker, HookTask


class MyHookWorker(HookWorker):
    """Example hook worker implementation."""

    def handle_task(self, task: HookTask) -> str:
        # TODO: Implement the actual hook task here
        # Example: process the playground directory
        return f"Task {task.id} for playground '{task.playground}' - not yet implemented"


if __name__ == '__main__':
    worker = MyHookWorker()
    worker.listen()