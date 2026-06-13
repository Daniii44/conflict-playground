import pytest

from state.redis import save as redis_save


def test_save_refuses_existing_file_without_force(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    save_path = stores_dir / "redis-saves" / "snapshot.ndjson"
    save_path.parent.mkdir(parents=True)
    save_path.write_text("existing\n", encoding="utf-8")

    connected = False

    def fail_if_connected():
        nonlocal connected
        connected = True
        raise AssertionError("Redis connection should not be opened before overwrite check")

    monkeypatch.setenv("STORES", str(stores_dir))
    monkeypatch.setattr(redis_save, "setup_data_redis_connection", fail_if_connected)
    monkeypatch.setattr("sys.argv", ["state-redis-save", "snapshot"])

    with pytest.raises(SystemExit) as error:
        redis_save.main()

    assert error.value.code == 1
    assert not connected
    assert save_path.read_text(encoding="utf-8") == "existing\n"


def test_save_allows_existing_file_with_force(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    save_path = stores_dir / "redis-saves" / "snapshot.ndjson"
    save_path.parent.mkdir(parents=True)
    save_path.write_text("existing\n", encoding="utf-8")

    monkeypatch.setenv("STORES", str(stores_dir))
    monkeypatch.setattr(redis_save, "setup_data_redis_connection", lambda: object())
    monkeypatch.setattr(redis_save, "write_save", lambda redis, output_path, patterns: output_path.write_text("new\n", encoding="utf-8") and 1)
    monkeypatch.setattr("sys.argv", ["state-redis-save", "snapshot", "--force"])

    redis_save.main()

    assert save_path.read_text(encoding="utf-8") == "new\n"
