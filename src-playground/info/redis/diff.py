#!/usr/bin/env python3

import argparse
import base64
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from info.redis._data import dump_key, resolve_save_path, setup_data_redis_connection


@dataclass(frozen=True)
class ChangedKey:
    key: bytes
    fields: tuple[str, ...]


@dataclass(frozen=True)
class RedisDiff:
    missing: tuple[bytes, ...]
    extra: tuple[bytes, ...]
    changed: tuple[ChangedKey, ...]

    def has_changes(self) -> bool:
        return bool(self.missing or self.extra or self.changed)


def decode_record_key(record: dict[str, Any]) -> bytes:
    return base64.b64decode(record["key_b64"].encode("ascii"))


def key_for_display(key: bytes) -> str:
    try:
        return key.decode("utf-8")
    except UnicodeDecodeError:
        return f"base64:{base64.b64encode(key).decode('ascii')}"


def load_save_records(path: Path) -> dict[bytes, dict[str, Any]]:
    records: dict[bytes, dict[str, Any]] = {}

    with open(path, "r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
                if record.get("format") != "redis-dump-v1":
                    raise ValueError(f"Unsupported record format: {record.get('format')!r}")
                key = decode_record_key(record)
            except Exception as error:
                raise ValueError(f"Failed to read {path}:{line_number}: {error}") from error

            if key in records:
                raise ValueError(f"Duplicate Redis key in save file at {path}:{line_number}: {key_for_display(key)}")

            records[key] = record

    return records


def collect_current_records(redis) -> dict[bytes, dict[str, Any]]:
    records: dict[bytes, dict[str, Any]] = {}

    for key in redis.scan_iter(match="*"):
        try:
            record = dump_key(redis, key)
        except Exception as error:
            logger.warning(f"Skipping Redis key because it could not be dumped: {error}")
            continue

        if record is None:
            continue

        records[key] = record

    return records


def compare_records(
    saved_records: dict[bytes, dict[str, Any]],
    current_records: dict[bytes, dict[str, Any]],
    *,
    include_ttl: bool = False,
) -> RedisDiff:
    saved_keys = set(saved_records)
    current_keys = set(current_records)
    common_keys = saved_keys & current_keys
    compared_fields = ("type", "dump_b64", "ttl_ms") if include_ttl else ("type", "dump_b64")

    changed: list[ChangedKey] = []
    for key in sorted(common_keys):
        changed_fields = tuple(
            field
            for field in compared_fields
            if saved_records[key].get(field) != current_records[key].get(field)
        )
        if changed_fields:
            changed.append(ChangedKey(key=key, fields=changed_fields))

    return RedisDiff(
        missing=tuple(sorted(saved_keys - current_keys)),
        extra=tuple(sorted(current_keys - saved_keys)),
        changed=tuple(changed),
    )


def print_diff(diff: RedisDiff) -> None:
    for key in diff.missing:
        print(f"missing {key_for_display(key)}")
    for key in diff.extra:
        print(f"extra {key_for_display(key)}")
    for changed in diff.changed:
        print(f"changed {key_for_display(changed.key)} ({', '.join(changed.fields)})")

    print(
        f"summary missing={len(diff.missing)} extra={len(diff.extra)} changed={len(diff.changed)}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Compare current Redis data keys with an NDJSON save file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  info-redis-diff all
  info-redis-diff all --include-ttl
""",
    )
    parser.add_argument("save_name", help="Name of the save file under $STORES/redis-saves")
    parser.add_argument(
        "--include-ttl",
        action="store_true",
        help="Also compare remaining TTL values. TTL is ignored by default because it changes over time.",
    )
    args = parser.parse_args()

    save_path = resolve_save_path(args.save_name)
    if not save_path.exists():
        logger.error(f"Redis save does not exist: {args.save_name}")
        sys.exit(2)

    try:
        saved_records = load_save_records(save_path)
    except ValueError as error:
        logger.error(str(error))
        sys.exit(2)

    redis = setup_data_redis_connection()
    current_records = collect_current_records(redis)
    diff = compare_records(saved_records, current_records, include_ttl=args.include_ttl)
    print_diff(diff)
    sys.exit(1 if diff.has_changes() else 0)


if __name__ == "__main__":
    main()
