import importlib.util
from pathlib import Path

import evaluation
from common.evaluation_models import MergeDiffEvaluation, MergeDiffOutput


REPLAY_DIFF_PATH = Path(evaluation.__path__[0]) / "replay-diff.py"
spec = importlib.util.spec_from_file_location("evaluation_replay_diff", REPLAY_DIFF_PATH)
replay_diff_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(replay_diff_module)


class FakeRedisJson:
    def __init__(self, payload_by_key):
        self.payload_by_key = payload_by_key

    def get(self, key):
        return self.payload_by_key.get(key)


class FakeRedis:
    def __init__(self, payload_by_key, keys=None):
        self.payload_by_key = payload_by_key
        self.keys = keys or []

    def json(self):
        return FakeRedisJson(self.payload_by_key)

    def scan_iter(self, match):
        prefix = match.removesuffix("*")
        return (key for key in self.keys if key.startswith(prefix))


def test_replay_diff_writes_recorded_diff_for_resolution_key(monkeypatch, capsys):
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    evaluation_key = "evaluation:merge:diff:owner/repo.git-actualsha:20260602T120000.000000Z"
    payload = MergeDiffEvaluation(
        resolution_key=resolution_key,
        proposed_to_actual_resolution_diffs={
            "exact": {
                "include_blank_lines": MergeDiffOutput(patch="\x1b[31m-diff\x1b[m\n"),
            },
        },
    ).model_dump(mode="json")
    monkeypatch.setattr(
        replay_diff_module,
        "setup_redis_connection",
        lambda: FakeRedis({evaluation_key: payload}),
    )

    exit_code = replay_diff_module.replay_diff(resolution_key)

    assert exit_code == 0
    assert capsys.readouterr().out == "\x1b[31m-diff\x1b[m\n"


def test_replay_diff_resolves_latest_resolution_for_playground(monkeypatch, capsys):
    latest_resolution = "resolution:conflict:owner/repo.git-actualsha:20260602T130000.000000Z"
    evaluation_key = "evaluation:merge:diff:owner/repo.git-actualsha:20260602T130000.000000Z"
    payload = MergeDiffEvaluation(
        resolution_key=latest_resolution,
        proposed_to_actual_resolution_patch="diff\n",
    ).model_dump(mode="json")
    keys = [
        "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z",
        latest_resolution,
    ]
    monkeypatch.setattr(
        replay_diff_module,
        "setup_redis_connection",
        lambda: FakeRedis({evaluation_key: payload}, keys=keys),
    )

    exit_code = replay_diff_module.replay_diff("owner/repo.git-actualsha")

    assert exit_code == 0
    assert capsys.readouterr().out == "diff\n"


def test_replay_diff_falls_back_to_legacy_diff_field(monkeypatch, capsys):
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    evaluation_key = "evaluation:merge:diff:owner/repo.git-actualsha:20260602T120000.000000Z"
    payload = {
        "resolution_key": resolution_key,
        "diff_to_actual_resolution": "legacy diff\n",
    }
    monkeypatch.setattr(
        replay_diff_module,
        "setup_redis_connection",
        lambda: FakeRedis({evaluation_key: payload}),
    )

    exit_code = replay_diff_module.replay_diff(resolution_key)

    assert exit_code == 0
    assert capsys.readouterr().out == "legacy diff\n"
