#!/usr/bin/env python3

import argparse
import redis
from uuid import UUID, uuid4
from pydantic import BaseModel

class HookTask(BaseModel):
    id: UUID
    playground: str

class HookResult(BaseModel):
    id: UUID
    result: str

def main():
    parser = argparse.ArgumentParser(description="Dispatch a hook task to the hook worker and wait for the result")
    parser.add_argument("playground_path", help="Path to the playground directory")
    args = parser.parse_args()

    r = redis.Redis(host='redis', port=6379, decode_responses=True)
    hookTask = HookTask(id=uuid4(), playground=args.playground_path)
    r.publish('to_hook', hookTask.model_dump_json())

    pubsub = r.pubsub()
    pubsub.subscribe('to_playground')


    for message in pubsub.listen():
        if message['type'] == 'message':
            result = HookResult.model_validate_json(message['data'])
            print(f"Playground: Got result: {result}")
            break


if __name__ == "__main__":
    main()
