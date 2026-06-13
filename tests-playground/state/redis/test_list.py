from state.redis import list as redis_list


def test_format_save_file_includes_name_size_and_modified_time(tmp_path, monkeypatch):
    save_file = tmp_path / "submodule-info-v1.ndjson"
    save_file.write_text("abc", encoding="utf-8")
    monkeypatch.setattr(redis_list, "format_modified_timestamp", lambda timestamp: "2026-06-13T12:00:00+00:00")

    assert redis_list.format_save_file(save_file) == "submodule-info-v1\t3\t2026-06-13T12:00:00+00:00"


def test_list_outputs_header_and_includes_underscore_saves(tmp_path, monkeypatch, capsys):
    save_dir = tmp_path / "redis-saves"
    save_dir.mkdir()
    (save_dir / "_submodule-info-v9.ndjson").write_text("hidden", encoding="utf-8")
    (save_dir / "submodule-info-v1.ndjson").write_text("visible", encoding="utf-8")

    monkeypatch.setattr(redis_list, "resolve_save_dir", lambda: save_dir)
    monkeypatch.setattr(redis_list, "format_modified_timestamp", lambda timestamp: "2026-06-13T12:00:00+00:00")

    redis_list.main()

    assert capsys.readouterr().out.splitlines() == [
        "name\tsize_bytes\tmodified",
        "_submodule-info-v9\t6\t2026-06-13T12:00:00+00:00",
        "submodule-info-v1\t7\t2026-06-13T12:00:00+00:00",
    ]
