#!/usr/bin/env python3

"""Common functionality for hook workers - Redis communication and shared models."""

from datetime import datetime
from redis.client import PubSub
from redis import Redis
import traceback
from uuid import UUID
from pydantic import BaseModel
from typing import Any, Callable, Optional


class HookTask(BaseModel):
    """Task message received from the playground."""
    id: UUID
    playground: str


class HookResult(BaseModel):
    """Result message sent back to the playground."""
    id: UUID
    result: dict[str, Any]


class HookWorker:
    """Base class for hook workers with Redis communication."""

    def __init__(self, redis_host: str = 'redis', redis_port: int = 6379):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self._redis: Optional[Redis] = None
        self._pubsub: Optional[PubSub] = None

    def log(self, message: str) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        print(f"{timestamp} [hook] {message}", flush=True)

    @property
    def redis(self) -> Redis:
        """Lazy initialization of Redis connection."""
        if self._redis is None:
            self._redis = Redis(
                host=self.redis_host,
                port=self.redis_port,
                decode_responses=True
            )
        return self._redis

    @property
    def pubsub(self) -> PubSub:
        """Lazy initialization of PubSub connection."""
        if self._pubsub is None:
            self._pubsub = self.redis.pubsub()
        return self._pubsub

    def listen(self, channel: str = 'to_hook', handler: Optional[Callable[[HookTask], str | dict[str, Any]]] = None):
        """
        Start listening for tasks on the specified channel.
        
        Args:
            channel: Redis channel to subscribe to
            handler: Optional callback function that takes a HookTask and returns a result payload.
                    If not provided, subclasses should override handle_task().
        """
        self.log(f"subscribing to Redis channel {channel!r} on {self.redis_host}:{self.redis_port}")
        self.pubsub.subscribe(channel)

        for message in self.pubsub.listen():
            message_type = message.get('type')
            if message_type != 'message':
                self.log(f"received Redis pubsub event type={message_type!r}")
                continue

            self.log("received hook task payload from Redis")
            task = HookTask.model_validate_json(message['data'])
            self.log(f"starting task id={task.id} playground={task.playground}")

            try:
                if handler:
                    result_msg = handler(task)
                else:
                    result_msg = self.handle_task(task)
            except Exception as error:
                self.log(
                    f"task id={task.id} playground={task.playground} raised "
                    f"{type(error).__name__}: {error}"
                )
                traceback.print_exc()
                result_msg = {
                    "message": f"Error: hook worker failed: {error}",
                    "error_type": type(error).__name__,
                }

            if isinstance(result_msg, str):
                result_msg = {"message": result_msg}

            result = HookResult(id=task.id, result=result_msg)
            self.log(
                f"publishing result for task id={task.id} playground={task.playground} "
                f"keys={sorted(result_msg.keys())}"
            )
            self.redis.publish('to_playground', result.model_dump_json())
            self.log(f"completed task id={task.id} playground={task.playground}")
            print(flush=True)

    def handle_task(self, task: HookTask) -> str | dict[str, Any]:
        """
        Override this method to implement custom task handling.
        
        Args:
            task: The task to process
            
        Returns:
            Result payload. Plain strings are wrapped as {"message": value}.
        """
        raise NotImplementedError("Subclasses must implement handle_task()")
