import base64
import os
from pathlib import Path
from typing import Any, Iterable

from redis import Redis


REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_SAVE_DIR_NAME = "redis-saves"
REDIS_SAVE_SUFFIX = ".ndjson"


def setup_data_redis_connection() -> Redis:
    return Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)


def resolve_save_dir() -> Path:
    stores_dir = Path(os.environ.get("STORES", "../../data/stores"))
    return stores_dir / REDIS_SAVE_DIR_NAME


def resolve_save_path(save_name: str) -> Path:
    if save_name != Path(save_name).name:
        raise ValueError("Save name must not contain path separators")

    file_name = save_name
    if not file_name.endswith(REDIS_SAVE_SUFFIX):
        file_name += REDIS_SAVE_SUFFIX

    return resolve_save_dir() / file_name


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _decode_key_for_display(key: bytes) -> str | None:
    try:
        return key.decode("utf-8")
    except UnicodeDecodeError:
        return None


def dump_key(redis: Redis, key: bytes) -> dict[str, Any] | None:
    key_type = redis.type(key)
    if key_type == b"none":
        return None

    ttl = redis.pttl(key)
    payload = redis.dump(key)
    if payload is None:
        return None

    record: dict[str, Any] = {
        "format": "redis-dump-v1",
        "key_b64": _encode(key),
        "type": key_type.decode("utf-8", errors="replace"),
        "dump_b64": _encode(payload),
        "ttl_ms": ttl if ttl > 0 else None,
    }
    display_key = _decode_key_for_display(key)
    if display_key is not None:
        record["key"] = display_key

    return record


def restore_key(redis: Redis, record: dict[str, Any]) -> None:
    if record.get("format") != "redis-dump-v1":
        raise ValueError(f"Unsupported Redis import record format: {record.get('format')!r}")

    key = _decode(record["key_b64"])
    payload = _decode(record["dump_b64"])
    ttl_ms = int(record["ttl_ms"] or 0)

    redis.restore(key, ttl_ms, payload, replace=True)


def iter_matching_keys(redis: Redis, patterns: Iterable[str]):
    seen = set()
    for pattern in patterns:
        for key in redis.scan_iter(match=pattern):
            if key in seen:
                continue
            seen.add(key)
            yield key
