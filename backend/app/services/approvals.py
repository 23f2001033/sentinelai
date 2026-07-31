from __future__ import annotations

import asyncio


class ApprovalGate:
    """Lets the agent loop block on a pending approval until a human resolves it."""

    def __init__(self) -> None:
        self._waiters: dict[int, asyncio.Event] = {}

    def register(self, approval_id: int) -> asyncio.Event:
        event = asyncio.Event()
        self._waiters[approval_id] = event
        return event

    def resolve(self, approval_id: int) -> bool:
        event = self._waiters.pop(approval_id, None)
        if event is None:
            return False
        event.set()
        return True

    def is_pending(self, approval_id: int) -> bool:
        return approval_id in self._waiters

    async def wait(self, approval_id: int, timeout: float) -> bool:
        event = self._waiters.get(approval_id)
        if event is None:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            self._waiters.pop(approval_id, None)
            return False


gate = ApprovalGate()
