import json

from state.clickhouse import export as clickhouse_export


def test_extract_conflict_columns_from_resolution_key():
    assert clickhouse_export.extract_conflict_columns(
        "resolution:conflict:owner/repo.git-merge123:20260609T120000.000000Z",
        {},
    ) == clickhouse_export.ConflictColumns(
        conflict_identifier="owner/repo.git-merge123:20260609T120000.000000Z",
        repo="owner/repo",
        merge_hash="merge123",
        conflict_timestamp="20260609T120000.000000Z",
    )


def test_extract_conflict_identifier_from_resolution_key():
    assert clickhouse_export.extract_conflict_identifier(
        "resolution:conflict:owner/repo.git-merge123:20260609T120000.000000Z",
        {},
    ) == "owner/repo.git-merge123:20260609T120000.000000Z"


def test_extract_conflict_identifier_from_evaluation_key():
    assert clickhouse_export.extract_conflict_identifier(
        "evaluation:merge:core:owner/repo.git-merge123:20260609T120000.000000Z",
        {},
    ) == "owner/repo.git-merge123:20260609T120000.000000Z"


def test_extract_conflict_identifier_from_info_key_omits_timestamp():
    assert clickhouse_export.extract_conflict_identifier(
        "info:conflict:core:owner/repo.git:merge123",
        {},
    ) == "owner/repo.git-merge123"


def test_extract_conflict_identifier_from_runtime_key_uses_payload_timestamp():
    assert clickhouse_export.extract_conflict_columns(
        "runtime:active_playground:owner/repo.git-merge123",
        {
            "configuration": {
                "resolution_start": "2026-06-09T12:00:00Z",
            }
        },
    ) == clickhouse_export.ConflictColumns(
        conflict_identifier="owner/repo.git-merge123:20260609T120000.000000Z",
        repo="owner/repo",
        merge_hash="merge123",
        conflict_timestamp="20260609T120000.000000Z",
    )


def test_extract_conflict_identifier_from_dataset_key():
    assert clickhouse_export.extract_conflict_identifier(
        "dataset:tilt:owner/repo.git:merge123",
        {},
    ) == "owner/repo.git-merge123"


def test_extract_conflict_identifier_falls_back_to_payload_fields():
    assert clickhouse_export.extract_conflict_columns(
        "custom:key",
        {
            "repo": "owner/repo.git",
            "merge_commit_oid": "merge123",
        },
    ) == clickhouse_export.ConflictColumns(
        conflict_identifier="owner/repo.git-merge123",
        repo="owner/repo",
        merge_hash="merge123",
        conflict_timestamp="",
    )


def test_insert_clickhouse_sends_conflict_identifier(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, *, data, auth, headers):
        captured["url"] = url
        captured["data"] = data.decode("utf-8")
        captured["auth"] = auth
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(clickhouse_export.requests, "post", fake_post)

    clickhouse_export.insert_clickhouse(
        [
            (
                "evaluation:merge:core:owner/repo.git-merge123:20260609T120000.000000Z",
                json.dumps({"value": 1}),
            )
        ]
    )

    assert "INSERT INTO default.redis_json FORMAT JSONEachRow" in captured["url"]
    assert captured["auth"] == ("default", "dev-dynha9-fenvYc-daqmeh")
    assert captured["headers"]["Content-Type"] == "application/x-ndjson"
    assert json.loads(captured["data"]) == {
        "key": "evaluation:merge:core:owner/repo.git-merge123:20260609T120000.000000Z",
        "conflict_identifier": "owner/repo.git-merge123:20260609T120000.000000Z",
        "repo": "owner/repo",
        "merge_hash": "merge123",
        "conflict_timestamp": "20260609T120000.000000Z",
        "content": {"value": 1},
    }
