from state.clickhouse import schema as clickhouse_schema
from state.clickhouse import ensure as clickhouse_ensure


def test_main_recreates_clickhouse_table(monkeypatch):
    actions = []

    monkeypatch.setattr(clickhouse_ensure, "drop_table", lambda: actions.append("drop"))
    monkeypatch.setattr(clickhouse_ensure, "create_table", lambda: actions.append("create"))

    clickhouse_ensure.main()

    assert actions == ["drop", "create"]


def test_schema_query_contains_explicit_conflict_columns_and_indexes():
    query = clickhouse_schema.create_table_query()

    assert "conflict_identifier String" in query
    assert "repo String" in query
    assert "merge_hash String" in query
    assert "conflict_timestamp String" in query
    assert "INDEX idx_conflict_identifier" in query
    assert "INDEX idx_repo" in query
    assert "INDEX idx_merge_hash" in query
    assert "INDEX idx_conflict_timestamp" in query
