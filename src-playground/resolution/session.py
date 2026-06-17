#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any

from loguru import logger

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection


def resolution_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if isinstance(content, dict):
        return content
    return payload


def session_export(content: dict[str, Any]) -> dict[str, Any]:
    hook_result = content.get("hook_result")
    if not isinstance(hook_result, dict):
        raise RuntimeError("Resolution has no hook_result")

    export = hook_result.get("opencode_session_export")
    if not isinstance(export, dict):
        raise RuntimeError("Resolution has no hook_result.opencode_session_export")

    error = export.get("error")
    if error:
        raise RuntimeError(f"Resolution session export has an error: {error}")

    data = export.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Resolution has no hook_result.opencode_session_export.data")

    return data


def part_log_line(part: dict[str, Any]) -> str:
    part_type = part.get("type")
    if part_type == "text":
        text = part.get("text")
        return text if isinstance(text, str) else ""

    if part_type == "patch":
        files = part.get("files")
        if isinstance(files, str):
            return files
        return json.dumps(files, sort_keys=True)

    if part_type == "tool":
        state = part.get("state")
        state = state if isinstance(state, dict) else {}
        input_data = state.get("input")
        input_data = input_data if isinstance(input_data, dict) else {}
        title = state.get("title") if isinstance(state.get("title"), str) else ""
        command = input_data.get("command") if isinstance(input_data.get("command"), str) else ""
        return f"{title} | Command: {command}"

    return f"[UNUSUAL TYPE: {part_type}]"


def simplified_session_lines(payload: dict[str, Any]) -> list[str]:
    data = session_export(resolution_content(payload))
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise RuntimeError("Resolution session export data has no messages list")

    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue

        info = message.get("info")
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue

        parts = message.get("parts")
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if isinstance(part_type, str) and part_type.startswith("step-"):
                continue
            lines.append(part_log_line(part))

    return lines


def resolution_session(redis, resolution_key: str) -> list[str]:
    payload = redis.json().get(resolution_key)
    if not payload:
        raise RuntimeError(f"No resolution found at {resolution_key}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Resolution {resolution_key} is not a JSON object")
    return simplified_session_lines(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a simplified assistant-only resolution session")
    parser.add_argument("resolution_key", help=f"Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    args = parser.parse_args()

    try:
        lines = resolution_session(setup_redis_connection(), args.resolution_key)
    except RuntimeError as error:
        logger.error("{}", error)
        return 1

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
