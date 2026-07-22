from state.clickhouse import schema as clickhouse_schema
from state.clickhouse import ensure as clickhouse_ensure


def test_main_recreates_clickhouse_table(monkeypatch):
    actions = []

    monkeypatch.setattr(clickhouse_ensure, "drop_views", lambda: actions.append("drop_views"))
    monkeypatch.setattr(clickhouse_ensure, "drop_table", lambda: actions.append("drop"))
    monkeypatch.setattr(clickhouse_ensure, "create_table", lambda: actions.append("create"))
    monkeypatch.setattr(clickhouse_ensure, "create_views", lambda: actions.append("create_views"))

    clickhouse_ensure.main()

    assert actions == ["drop_views", "drop", "create", "create_views"]


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


def test_overview_base_view_uses_group_dimensions_and_current_schesch_keys():
    query = clickhouse_schema.overview_base_view_query()

    assert "CREATE VIEW IF NOT EXISTS default.redis_json_overview_base AS" in query
    assert "group_label" in query
    assert "subdataset" in query
    assert "llm" in query
    assert "evaluation:merge:schesch-original:" in query
    assert "evaluation:merge:schesch-generated:" in query
    assert "evaluation:merge:schesch:" not in query


def test_overview_queries_reference_base_view():
    chart_query = clickhouse_schema.overview_chart_view_query()
    table_query = clickhouse_schema.overview_table_view_query()

    assert "FROM default.redis_json_overview_base" in chart_query
    assert "FROM default.redis_json_overview_base" in table_query
