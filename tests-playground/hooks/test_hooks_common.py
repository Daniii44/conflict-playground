import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID


def load_hooks_common_module():
    repo_root = Path(__file__).resolve().parents[2]
    hooks_path = repo_root / "src-hooks"
    sys.path.insert(0, str(hooks_path))
    try:
        spec = importlib.util.spec_from_file_location(
            "hooks_common",
            hooks_path / "hooks_common.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(hooks_path))


class FakePubSub:
    def __init__(self, messages):
        self.messages = messages
        self.subscribed_channels = []

    def subscribe(self, channel):
        self.subscribed_channels.append(channel)

    def listen(self):
        return iter(self.messages)


class FakeRedis:
    def __init__(self):
        self.published = []

    def publish(self, channel, message):
        self.published.append((channel, message))


def test_listen_publishes_error_result_when_handler_raises():
    module = load_hooks_common_module()
    task_id = UUID("00000000-0000-0000-0000-000000000001")
    task = module.HookTask(id=task_id, playground="example-project-abc123")
    worker = module.HookWorker()
    worker._redis = FakeRedis()
    worker._pubsub = FakePubSub(
        [
            {
                "type": "message",
                "data": task.model_dump_json(),
            }
        ]
    )

    def bad_handler(received_task):
        assert received_task == task
        raise RuntimeError("bad hook")

    worker.listen(handler=bad_handler)

    assert worker._pubsub.subscribed_channels == ["to_hook"]
    assert len(worker._redis.published) == 1
    channel, message = worker._redis.published[0]
    assert channel == "to_playground"
    payload = json.loads(message)
    assert payload["id"] == str(task_id)
    assert payload["result"]["message"] == "Error: hook worker failed: bad hook"
    assert payload["result"]["error_type"] == "RuntimeError"
