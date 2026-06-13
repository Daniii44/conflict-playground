from state.redis._data import parse_semantic_save_path, resolve_sync_save_paths


def touch_save(stores_dir, name: str):
    save_path = stores_dir / "redis-saves" / f"{name}.ndjson"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text("", encoding="utf-8")
    return save_path


def test_parse_semantic_save_path_allows_hyphenated_playbook_names(tmp_path):
    save = parse_semantic_save_path(tmp_path / "merge-submodule-info-v2.3.ndjson")

    assert save is not None
    assert save.playbook == "merge-submodule"
    assert save.data_type == "info"
    assert save.major == 2
    assert save.minor == 3


def test_parse_semantic_save_path_defaults_missing_minor_to_zero(tmp_path):
    save = parse_semantic_save_path(tmp_path / "submodule-resolution-v1.ndjson")

    assert save is not None
    assert save.major == 1
    assert save.minor == 0


def test_resolve_sync_save_paths_prefers_exact_existing_save(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    explicit_save = touch_save(stores_dir, "submodule")
    touch_save(stores_dir, "submodule-info-v1")

    monkeypatch.setenv("STORES", str(stores_dir))

    assert resolve_sync_save_paths("submodule") == [explicit_save]


def test_resolve_sync_save_paths_selects_latest_major_and_latest_minor_per_type(monkeypatch, tmp_path):
    stores_dir = tmp_path / "stores"
    touch_save(stores_dir, "submodule-info-v1.9")
    touch_save(stores_dir, "submodule-resolution-v1.5")
    touch_save(stores_dir, "submodule-info-v2")
    selected_resolution = touch_save(stores_dir, "submodule-resolution-v2.1")
    selected_info = touch_save(stores_dir, "submodule-info-v2.2")
    selected_evaluation = touch_save(stores_dir, "submodule-evaluation-v2")
    selected_metrics = touch_save(stores_dir, "submodule-metrics-v2.3")
    touch_save(stores_dir, "other-info-v9")

    monkeypatch.setenv("STORES", str(stores_dir))

    assert resolve_sync_save_paths("submodule") == [
        selected_info,
        selected_resolution,
        selected_evaluation,
        selected_metrics,
    ]
