from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Approval, Run, SpendRecord
from ..schemas import SpendSummaryOut
from ..services.events import GLOBAL_CHANNEL, bus

router = APIRouter(tags=["telemetry"])

HEARTBEAT_SECONDS = 25


@router.get("/api/spend/summary", response_model=SpendSummaryOut)
async def spend_summary(session: AsyncSession = Depends(get_session)):
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(SpendRecord.cost_usd), 0.0),
                func.coalesce(func.sum(SpendRecord.input_tokens), 0),
                func.coalesce(func.sum(SpendRecord.output_tokens), 0),
                func.count(SpendRecord.id),
            )
        )
    ).one()

    per_run = await session.execute(
        select(
            SpendRecord.run_id,
            func.coalesce(func.sum(SpendRecord.cost_usd), 0.0),
            func.count(SpendRecord.id),
        )
        .group_by(SpendRecord.run_id)
        .order_by(SpendRecord.run_id.desc())
        .limit(20)
    )

    return SpendSummaryOut(
        total_usd=round(float(totals[0]), 6),
        total_input_tokens=int(totals[1]),
        total_output_tokens=int(totals[2]),
        calls=int(totals[3]),
        by_run=[
            {"run_id": row[0], "cost_usd": round(float(row[1]), 6), "calls": int(row[2])}
            for row in per_run
        ],
    )


@router.get("/api/stats")
async def dashboard_stats(session: AsyncSession = Depends(get_session)):
    run_counts = await session.execute(
        select(Run.status, func.count(Run.id)).group_by(Run.status)
    )
    pending = await session.scalar(
        select(func.count(Approval.id)).where(Approval.status == "pending")
    )
    spend = await session.scalar(select(func.coalesce(func.sum(SpendRecord.cost_usd), 0.0)))
    return {
        "runs_by_status": {row[0]: row[1] for row in run_counts},
        "pending_approvals": int(pending or 0),
        "total_spend_usd": round(float(spend or 0.0), 6),
    }


async def _stream(websocket: WebSocket, channel: int) -> None:
    await websocket.accept()
    try:
        async with bus.subscribe(channel) as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "heartbeat"})
                    continue
                await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close()


@router.websocket("/ws/runs/{run_id}")
async def run_stream(websocket: WebSocket, run_id: int) -> None:
    await _stream(websocket, run_id)


@router.websocket("/ws/all")
async def global_stream(websocket: WebSocket) -> None:
    await _stream(websocket, GLOBAL_CHANNEL)
