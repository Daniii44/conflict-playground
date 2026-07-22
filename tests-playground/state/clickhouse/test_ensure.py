from state.clickhouse import ensure as clickhouse_ensure


def test_main_recreates_clickhouse_table(monkeypatch):
    actions = []

    monkeypatch.setattr(clickhouse_ensure, "drop_table", lambda: actions.append("drop"))
    monkeypatch.setattr(clickhouse_ensure, "create_table", lambda: actions.append("create"))

    clickhouse_ensure.main()

    assert actions == ["drop", "create"]
