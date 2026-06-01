import importlib.util
from pathlib import Path

import evaluation
from common.active_playground_models import Configuration
from common.evaluation_models import ConflictEvaluation, Evaluation, ProposedResolution


REPLAY_DIFF_PATH = Path(evaluation.__path__[0]) / "replay-diff.py"
spec = importlib.util.spec_from_file_location("evaluation_replay_diff", REPLAY_DIFF_PATH)
replay_diff_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(replay_diff_module)


class FakeRedisJson:
    def __init__(self, payload):
        self.payload = payload

    def get(self, key):
        return self.payload


class FakeRedis:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return FakeRedisJson(self.payload)


def test_replay_diff_writes_recorded_diff(monkeypatch, capsys):
    payload = ConflictEvaluation(
        configuration=Configuration(
            hook_type="manual-cli",
            playground_version="test",
            volume_type="bind-mount",
            resolution_start="2026-06-01T00:00:00",
        ),
        result=Evaluation(duration_seconds=1.0, incomplete_merge=False, perfect_match=False),
        proposed_resolution=ProposedResolution(diff_to_actual_resolution="\x1b[31m-diff\x1b[m\n"),
    ).model_dump(mode="json")
    monkeypatch.setattr(replay_diff_module, "setup_redis_connection", lambda: FakeRedis(payload))

    exit_code = replay_diff_module.replay_diff("owner/repo.git-actual-sha")

    assert exit_code == 0
    assert capsys.readouterr().out == "\x1b[31m-diff\x1b[m\n"
