from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..enums import AuditKind
from ..models import AuditEvent
from .events import bus


async def record(
    session: AsyncSession,
    *,
    kind: AuditKind,
    message: str,
    run_id: int | None = None,
    step_id: int | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "system",
) -> AuditEvent:
    event = AuditEvent(
        run_id=run_id,
        step_id=step_id,
        kind=str(kind),
        message=message,
        payload=payload or {},
        actor=actor,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    await bus.publish(
        run_id or 0,
        {
            "type": "audit",
            "id": event.id,
            "run_id": run_id,
            "step_id": step_id,
            "kind": str(kind),
            "message": message,
            "payload": event.payload,
            "actor": actor,
            "created_at": event.created_at.isoformat(),
        },
    )
    return event
