#!/usr/bin/env python3

"""Common functionality for hook workers - Redis communication and shared models."""

from redis.client import PubSub
from redis import Redis
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
        self.pubsub.subscribe(channel)

        for message in self.pubsub.listen():
            if message['type'] == 'message':
                print(f"Hook Base: Conflict Resolution Playground Set Up")
                task = HookTask.model_validate_json(message['data'])

                # Get result from handler or subclass method
                if handler:
                    result_msg = handler(task)
                else:
                    result_msg = self.handle_task(task)

                if isinstance(result_msg, str):
                    result_msg = {"message": result_msg}

                result = HookResult(id=task.id, result=result_msg)
                self.redis.publish('to_playground', result.model_dump_json())
                print(f"Hook Base: Conflict Resolution Playground Completed")
                print()

    def handle_task(self, task: HookTask) -> str | dict[str, Any]:
        """
        Override this method to implement custom task handling.
        
        Args:
            task: The task to process
            
        Returns:
            Result payload. Plain strings are wrapped as {"message": value}.
        """
        raise NotImplementedError("Subclasses must implement handle_task()")
