import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from redis import Redis


REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_SAVE_DIR_NAME = "redis-saves"
REDIS_SAVE_SUFFIX = ".ndjson"
SEMANTIC_SAVE_NAME = "<playbook>-<type>-v<major>[.<minor>]"
SEMANTIC_SAVE_PATTERN = re.compile(
    r"^(?P<playbook>.+)-(?P<data_type>[^-]+)-v(?P<major>\d+)(?:\.(?P<minor>\d+))?$"
)
SEMANTIC_TYPE_ORDER = ("info", "resolution", "evaluation")


@dataclass(frozen=True)
class SemanticSave:
    path: Path
    name: str
    playbook: str
    data_type: str
    major: int
    minor: int


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


def parse_semantic_save_path(save_path: Path) -> SemanticSave | None:
    name = save_path.name.removesuffix(REDIS_SAVE_SUFFIX)
    match = SEMANTIC_SAVE_PATTERN.fullmatch(name)
    if match is None:
        return None

    minor = match.group("minor")
    return SemanticSave(
        path=save_path,
        name=name,
        playbook=match.group("playbook"),
        data_type=match.group("data_type"),
        major=int(match.group("major")),
        minor=int(minor) if minor is not None else 0,
    )


def iter_semantic_saves() -> Iterable[SemanticSave]:
    save_dir = resolve_save_dir()
    if not save_dir.exists():
        return

    for save_path in sorted(save_dir.glob(f"*{REDIS_SAVE_SUFFIX}")):
        if save_path.name.startswith("_"):
            continue

        semantic_save = parse_semantic_save_path(save_path)
        if semantic_save is not None:
            yield semantic_save


def semantic_save_sort_key(save: SemanticSave):
    try:
        type_order = SEMANTIC_TYPE_ORDER.index(save.data_type)
    except ValueError:
        type_order = len(SEMANTIC_TYPE_ORDER)

    return (type_order, save.data_type, save.name)


def resolve_sync_save_paths(save_or_playbook: str) -> list[Path]:
    explicit_path = resolve_save_path(save_or_playbook)
    if explicit_path.exists():
        return [explicit_path]

    candidates = [save for save in iter_semantic_saves() if save.playbook == save_or_playbook]
    if not candidates:
        raise FileNotFoundError(
            f"No Redis save exists for {save_or_playbook!r}. "
            f"Use an exact save name or a playbook with saves named {SEMANTIC_SAVE_NAME}."
        )

    latest_major = max(save.major for save in candidates)
    latest_by_type: dict[str, SemanticSave] = {}
    for save in candidates:
        if save.major != latest_major:
            continue

        current = latest_by_type.get(save.data_type)
        if current is None or (save.minor, save.name) > (current.minor, current.name):
            latest_by_type[save.data_type] = save

    return [save.path for save in sorted(latest_by_type.values(), key=semantic_save_sort_key)]


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
