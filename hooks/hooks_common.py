#!/usr/bin/env python3

"""Common functionality for hook workers - Redis communication and shared models."""

from redis.client import PubSub
from redis import Redis
from uuid import UUID
from pydantic import BaseModel
from typing import Callable, Optional


class HookTask(BaseModel):
    """Task message received from the playground."""
    id: UUID
    playground: str


class HookResult(BaseModel):
    """Result message sent back to the playground."""
    id: UUID
    result: str


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

    def listen(self, channel: str = 'to_hook', handler: Optional[Callable[[HookTask], str]] = None):
        """
        Start listening for tasks on the specified channel.
        
        Args:
            channel: Redis channel to subscribe to
            handler: Optional callback function that takes a HookTask and returns a result string.
                    If not provided, subclasses should override handle_task().
        """
        self.pubsub.subscribe(channel)
        print(f"Hook Worker: Ready and listening for tasks on '{channel}'...")

        for message in self.pubsub.listen():
            if message['type'] == 'message':
                task = HookTask.model_validate_json(message['data'])
                print(f"Hook Worker: Got task: {task}")

                # Get result from handler or subclass method
                if handler:
                    result_msg = handler(task)
                else:
                    result_msg = self.handle_task(task)

                result = HookResult(id=task.id, result=result_msg)
                self.redis.publish('to_playground', result.model_dump_json())
                print(f"Hook Worker: Result sent back: {result}")

    def handle_task(self, task: HookTask) -> str:
        """
        Override this method to implement custom task handling.
        
        Args:
            task: The task to process
            
        Returns:
            Result message string
        """
        raise NotImplementedError("Subclasses must implement handle_task()")