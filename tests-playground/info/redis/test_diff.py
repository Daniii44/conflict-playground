import base64
import json

import pytest

from info.redis import diff as redis_diff


def make_record(key: bytes, *, key_type: str = "string", dump: str = "payload", ttl_ms=None):
    record = {
        "format": "redis-dump-v1",
        "key_b64": base64.b64encode(key).decode("ascii"),
        "type": key_type,
        "dump_b64": dump,
        "ttl_ms": ttl_ms,
    }
    try:
        record["key"] = key.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return record


def test_compare_records_reports_missing_extra_and_changed_keys():
    saved = {
        b"missing": make_record(b"missing"),
        b"changed": make_record(b"changed", dump="old"),
        b"same": make_record(b"same"),
    }
    current = {
        b"extra": make_record(b"extra"),
        b"changed": make_record(b"changed", dump="new"),
        b"same": make_record(b"same"),
    }

    diff = redis_diff.compare_records(saved, current)

    assert diff.missing == (b"missing",)
    assert diff.extra == (b"extra",)
    assert diff.changed == (redis_diff.ChangedKey(key=b"changed", fields=("dump_b64",)),)
    assert diff.has_changes()


def test_compare_records_ignores_ttl_by_default():
    saved = {b"key": make_record(b"key", ttl_ms=5000)}
    current = {b"key": make_record(b"key", ttl_ms=1000)}

    diff = redis_diff.compare_records(saved, current)

    assert diff == redis_diff.RedisDiff(missing=(), extra=(), changed=())
    assert not diff.has_changes()


def test_compare_records_can_include_ttl():
    saved = {b"key": make_record(b"key", ttl_ms=5000)}
    current = {b"key": make_record(b"key", ttl_ms=1000)}

    diff = redis_diff.compare_records(saved, current, include_ttl=True)

    assert diff.changed == (redis_diff.ChangedKey(key=b"key", fields=("ttl_ms",)),)


def test_load_save_records_rejects_duplicate_keys(tmp_path):
    save_path = tmp_path / "save.ndjson"
    record = make_record(b"key")
    save_path.write_text(
        f"{json.dumps(record)}\n{json.dumps(record)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate Redis key"):
        redis_diff.load_save_records(save_path)
