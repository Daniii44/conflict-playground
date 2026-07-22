#!/usr/bin/env python3

import argparse
from datetime import datetime
import redis
import time
from uuid import UUID, uuid4
from pydantic import BaseModel
from typing import Any

from common.redis_util import RUNTIME_ACTIVE_PLAYGROUND_PREFIX

class HookTask(BaseModel):
    id: UUID
    playground: str

class HookResult(BaseModel):
    id: UUID
    result: dict[str, Any]


def log(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"{timestamp} [playground-hook-dispatch] {message}", flush=True)

def main():
    parser = argparse.ArgumentParser(description="Dispatch a hook task to the hook worker and wait for the result")
    parser.add_argument("playground_path", help="Path to the playground directory")
    args = parser.parse_args()

    r = redis.Redis(host='redis', port=6379, decode_responses=True)
    hookTask = HookTask(id=uuid4(), playground=args.playground_path)
    log(f"dispatching hook task id={hookTask.id} playground={hookTask.playground}")
    r.publish('to_hook', hookTask.model_dump_json())
    log(f"published task id={hookTask.id} to channel 'to_hook'")

    pubsub = r.pubsub()
    pubsub.subscribe('to_playground')
    log("subscribed to Redis channel 'to_playground' and waiting for hook result")

    started_waiting = time.monotonic()
    last_wait_log = started_waiting

    while True:
        message = pubsub.get_message(timeout=1.0)
        if message is None:
            now = time.monotonic()
            if now - last_wait_log >= 30:
                log(
                    f"still waiting for hook result id={hookTask.id} "
                    f"after {now - started_waiting:.1f}s"
                )
                last_wait_log = now
            continue

        if message['type'] != 'message':
            log(f"received Redis pubsub event type={message['type']!r}")
            continue

        result = HookResult.model_validate_json(message['data'])
        if result.id != hookTask.id:
            log(f"ignoring result for unrelated task id={result.id}")
            continue
        active_playground_key = f"{RUNTIME_ACTIVE_PLAYGROUND_PREFIX}{args.playground_path}"
        if r.exists(active_playground_key):
            log(f"persisting hook result on active playground key {active_playground_key}")
            r.json().set(active_playground_key, "$.hook_result", result.result)
        else:
            log(f"active playground key missing while storing hook result: {active_playground_key}")
        log(
            f"received matching hook result for task id={result.id} "
            f"after {time.monotonic() - started_waiting:.1f}s keys={sorted(result.result.keys())}"
        )
        print(f"Playground: Got result: {result}")
        break


if __name__ == "__main__":
    main()
