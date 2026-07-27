#!/usr/bin/env python3

import argparse
import sys
from typing import Any

from common.redis_util import RESOLUTION_CONFLICT_PREFIX, setup_redis_connection

TIMEOUT_ERROR_PREFIX = "Error: opencode timed out"


def normalize_key(key) -> str:
    return key.decode() if isinstance(key, bytes) else key


def list_resolution_keys(redis) -> list[str]:
    return sorted(normalize_key(key) for key in redis.scan_iter(match=f"{RESOLUTION_CONFLICT_PREFIX}*"))


def resolution_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if isinstance(content, dict):
        return content
    return payload


def resolution_model_ids(payload: dict[str, Any]) -> set[str]:
    content = resolution_content(payload)
    hook_result = content.get("hook_result")
    if not isinstance(hook_result, dict):
        return set()

    export = hook_result.get("opencode_session_export")
    if not isinstance(export, dict):
        return set()

    data = export.get("data")
    if not isinstance(data, dict):
        return set()

    messages = data.get("messages")
    if not isinstance(messages, list):
        return set()

    model_ids: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        info = message.get("info")
        if not isinstance(info, dict):
            continue
        model_id = info.get("modelID")
        if isinstance(model_id, str) and model_id:
            model_ids.add(model_id)

    return model_ids


def key_matches_model(redis, key: str, model: str) -> bool:
    payload = redis.json().get(key)
    if not isinstance(payload, dict):
        return False
    return model in resolution_model_ids(payload)


def proposed_resolution_error(payload: dict[str, Any]) -> str | None:
    content = resolution_content(payload)
    proposed_resolution = content.get("proposed_resolution")
    if not isinstance(proposed_resolution, dict):
        return None
    error = proposed_resolution.get("error")
    return error if isinstance(error, str) and error else None


def key_has_non_timeout_error(redis, key: str) -> bool:
    payload = redis.json().get(key)
    if not isinstance(payload, dict):
        return False

    error = proposed_resolution_error(payload)
    if error is None:
        return False

    return not error.startswith(TIMEOUT_ERROR_PREFIX)


def prune_resolution(
    redis,
    key: str | None = None,
    prune_all: bool = False,
    model: str | None = None,
    non_timeout_error: bool = False,
) -> list[str]:
    if key:
        keys = [key]
    elif prune_all or model or non_timeout_error:
        keys = list_resolution_keys(redis)
    else:
        raise RuntimeError("Specify a resolution key, --all, --model, or --non-timeout-error")

    if model:
        keys = [candidate for candidate in keys if key_matches_model(redis, candidate, model)]
    if non_timeout_error:
        keys = [candidate for candidate in keys if key_has_non_timeout_error(redis, candidate)]

    if keys:
        redis.delete(*keys)

    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove saved conflict resolution Redis keys")
    parser.add_argument("-a", "--all", "-all", action="store_true", dest="prune_all", help="Remove all saved resolutions")
    parser.add_argument("-m", "--model", help="Remove only saved resolutions for the given modelID")
    parser.add_argument(
        "--non-timeout-error",
        action="store_true",
        help="Remove only saved resolutions whose proposed_resolution.error is not an opencode timeout",
    )
    parser.add_argument("key", nargs="?", help=f"Resolution Redis key, usually starting with {RESOLUTION_CONFLICT_PREFIX}")
    args = parser.parse_args()

    if args.key and (args.prune_all or args.model or args.non_timeout_error):
        parser.error("Specify either a key or filters (--all/--model/--non-timeout-error), not both")

    try:
        deleted_keys = prune_resolution(
            redis=setup_redis_connection(),
            key=args.key,
            prune_all=args.prune_all,
            model=args.model,
            non_timeout_error=args.non_timeout_error,
        )
    except RuntimeError as error:
        parser.error(str(error))
        return 2

    for key in deleted_keys:
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
