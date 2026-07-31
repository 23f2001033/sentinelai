from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

GLOBAL_CHANNEL = 0
QUEUE_MAXSIZE = 256


class EventBus:
    """In-process pub/sub so WebSocket clients can follow a run as it happens.

    Every event is also persisted as an AuditEvent, so a dropped subscriber loses
    live updates but never loses history.
    """

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, channel: int) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers[channel].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[channel].discard(queue)
            if not self._subscribers[channel]:
                self._subscribers.pop(channel, None)

    async def publish(self, channel: int, event: dict[str, Any]) -> None:
        for target in {channel, GLOBAL_CHANNEL}:
            for queue in list(self._subscribers.get(target, ())):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # A stalled subscriber must not block the agent loop.
                    pass


bus = EventBus()
