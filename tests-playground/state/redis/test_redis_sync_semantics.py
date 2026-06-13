from pathlib import Path

from state.redis import sync as redis_sync


def test_sync_cancel_exits_before_connecting_to_redis(monkeypatch):
    connected = False

    def fail_if_connected():
        nonlocal connected
        connected = True
        raise AssertionError("Redis connection should not be opened after cancellation")

    monkeypatch.setattr(redis_sync, "collect_save_paths", lambda save_names: [Path("submodule-info-v1.ndjson")])
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    monkeypatch.setattr(redis_sync, "setup_data_redis_connection", fail_if_connected)
    monkeypatch.setattr("sys.argv", ["state-redis-sync", "submodule"])

    assert redis_sync.main() == 1
    assert not connected
