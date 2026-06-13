import pytest

from state.redis.merge import merge_save_files


def write_save(stores_dir, save_name: str, content: str):
    save_path = stores_dir / "redis-saves" / f"{save_name}.ndjson"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    return save_path


def test_merge_save_files_writes_all_non_empty_records(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    write_save(stores_dir, "submodule-info-v1", '{"key":"info-1"}\n\n{"key":"info-2"}\n')
    write_save(stores_dir, "submodule-resolution-v1", '{"key":"resolution-1"}\n')

    monkeypatch.setenv("STORES", str(stores_dir))

    assert merge_save_files("submodule-info-v1", "submodule-resolution-v1", "submodule-state-v1") == 3
    assert (stores_dir / "redis-saves" / "submodule-state-v1.ndjson").read_text(encoding="utf-8") == (
        '{"key":"info-1"}\n'
        '{"key":"info-2"}\n'
        '{"key":"resolution-1"}\n'
    )


def test_merge_save_files_rejects_output_matching_an_input(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    write_save(stores_dir, "submodule-info-v1", '{"key":"info"}\n')
    write_save(stores_dir, "submodule-resolution-v1", '{"key":"resolution"}\n')

    monkeypatch.setenv("STORES", str(stores_dir))

    with pytest.raises(ValueError, match="output must be different"):
        merge_save_files("submodule-info-v1", "submodule-resolution-v1", "submodule-info-v1")
