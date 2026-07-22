import base64
from urllib import error

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


def test_overview_queries_are_loaded_from_assets():
    assert clickhouse_schema.load_sql_asset("overview-base.sql") == clickhouse_schema.overview_base_view_query()
    assert clickhouse_schema.load_sql_asset("overview-chart.sql") == clickhouse_schema.overview_chart_view_query()
    assert clickhouse_schema.load_sql_asset("overview-table.sql") == clickhouse_schema.overview_table_view_query()


def test_sql_loader_prefers_container_path(tmp_path, monkeypatch):
    container_dir = tmp_path / "root-sql"
    workspace_dir = tmp_path / "workspace-sql"
    container_dir.mkdir()
    workspace_dir.mkdir()
    (container_dir / "overview-base.sql").write_text("container", encoding="utf-8")
    (workspace_dir / "overview-base.sql").write_text("workspace", encoding="utf-8")

    monkeypatch.setattr(clickhouse_schema, "CONTAINER_SQL_DIR", container_dir)
    monkeypatch.setattr(clickhouse_schema, "ASSETS_SQL_DIR", workspace_dir)

    assert clickhouse_schema.load_sql_asset("overview-base.sql") == "container"


def test_run_query_posts_sql_in_body(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b""

    def fake_urlopen(query_request):
        captured["url"] = query_request.full_url
        captured["data"] = query_request.data
        captured["method"] = query_request.get_method()
        captured["headers"] = dict(query_request.header_items())
        return FakeResponse()

    monkeypatch.setattr(clickhouse_schema.request, "urlopen", fake_urlopen)

    clickhouse_schema.run_query("SELECT 1")

    assert captured["url"] == "http://clickhouse:8123"
    assert captured["data"] == b"SELECT 1"
    assert captured["method"] == "POST"
    assert captured["headers"]["Content-type"] == "text/plain; charset=utf-8"
    assert captured["headers"]["Authorization"] == (
        "Basic "
        + base64.b64encode(b"default:dev-dynha9-fenvYc-daqmeh").decode("ascii")
    )


def test_run_query_prints_error_body_before_raise(monkeypatch, capsys):
    def fake_urlopen(_query_request):
        raise error.HTTPError(
            url="http://clickhouse:8123",
            code=400,
            msg="boom",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(clickhouse_schema.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        error.HTTPError,
        "read",
        lambda self: b"Code: 47. DB::Exception: broken query",
    )

    try:
        clickhouse_schema.run_query("SELECT 1")
    except error.HTTPError:
        pass
    else:
        raise AssertionError("Expected HTTPError")

    captured = capsys.readouterr()
    assert "Code: 47. DB::Exception: broken query" in captured.err


def test_clickhouse_settings_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_URL", "http://127.0.0.1:18123")
    monkeypatch.setenv("CLICKHOUSE_DB", "custom_db")
    monkeypatch.setenv("CLICKHOUSE_USER", "custom_user")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "custom_password")
    monkeypatch.setenv("CLICKHOUSE_TABLE", "custom_table")

    monkeypatch.setattr(clickhouse_schema, "CLICKHOUSE_URL", "http://127.0.0.1:18123")
    monkeypatch.setattr(clickhouse_schema, "CLICKHOUSE_DB", "custom_db")
    monkeypatch.setattr(clickhouse_schema, "CLICKHOUSE_USER", "custom_user")
    monkeypatch.setattr(clickhouse_schema, "CLICKHOUSE_PASSWORD", "custom_password")
    monkeypatch.setattr(clickhouse_schema, "CLICKHOUSE_TABLE", "custom_table")

    assert clickhouse_schema.CLICKHOUSE_URL == "http://127.0.0.1:18123"
    assert clickhouse_schema.CLICKHOUSE_DB == "custom_db"
    assert clickhouse_schema.CLICKHOUSE_USER == "custom_user"
    assert clickhouse_schema.CLICKHOUSE_PASSWORD == "custom_password"
    assert clickhouse_schema.CLICKHOUSE_TABLE == "custom_table"


def test_overview_base_view_aliases_metric_dimensions():
    query = clickhouse_schema.overview_base_view_query()

    assert "rd.repo AS repo" in query
    assert "rd.merge_hash AS merge_hash" in query
    assert "class_source.repo AS repo" in query
    assert "rd.repo AS repo,\n            rd.merge_hash AS merge_hash" in query


def test_overview_base_view_aliases_base_dimensions():
    query = clickhouse_schema.overview_base_view_query()

    assert "base_merges AS (" in query
    assert "rd.repo AS repo" in query
    assert "rd.merge_hash AS merge_hash" in query
    assert "rd.group_label AS group_label" in query
    assert "b.group_label AS group_label" in query
