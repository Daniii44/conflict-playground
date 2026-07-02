import os
import subprocess

from loguru import logger


def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_ASKPASS"] = "false"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    env["SSH_ASKPASS"] = "false"
    return env


def capture_git(
    *args: str,
    check: bool = True,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    logger.debug("Running git command: git {}", " ".join(args))
    command_env = git_env()
    if env:
        command_env.update(env)
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=command_env,
    )


def capture_git_bytes(
    *args: str,
    check: bool = True,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    logger.debug("Running git command: git {}", " ".join(args))
    command_env = git_env()
    if env:
        command_env.update(env)
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        cwd=cwd,
        env=command_env,
    )


def stream_git(
    *args: str,
    check: bool = False,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    logger.debug("Running git command: git {}", " ".join(args))
    command_env = git_env()
    if env:
        command_env.update(env)
    return subprocess.run(
        ["git", *args],
        check=check,
        cwd=cwd,
        env=command_env,
    )
