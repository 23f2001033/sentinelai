from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..enums import AuditKind, RunStatus
from ..models import Agent, AuditEvent, Run, Step
from ..schemas import AuditEventOut, RunDetailOut, RunIn, RunOut
from ..services import audit
from ..services.runner import start_run

router = APIRouter(prefix="/api/runs", tags=["runs"])

_background: set[asyncio.Task] = set()


@router.get("", response_model=list[RunOut])
async def list_runs(limit: int = 50, session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Run).order_by(Run.id.desc()).limit(limit))
    return list(result)


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(payload: RunIn, session: AsyncSession = Depends(get_session)):
    if await session.get(Agent, payload.agent_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    run = Run(**payload.model_dump())
    session.add(run)
    await session.commit()
    await session.refresh(run)

    task = asyncio.create_task(start_run(run.id))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return run


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)):
    run = await session.scalar(
        select(Run)
        .where(Run.id == run_id)
        .options(
            selectinload(Run.steps).selectinload(Step.decision),
            selectinload(Run.steps).selectinload(Step.approval),
        )
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.get("/{run_id}/audit", response_model=list[AuditEventOut])
async def get_run_audit(run_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.scalars(
        select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)
    )
    return list(result)


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: int, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    if run.status in {str(RunStatus.COMPLETED), str(RunStatus.FAILED), str(RunStatus.CANCELLED)}:
        return run

    run.status = str(RunStatus.CANCELLED)
    run.summary = "Cancelled by the operator."
    await session.commit()
    await session.refresh(run)
    await audit.record(
        session,
        kind=AuditKind.RUN_FINISHED,
        message="Run cancelled by the operator.",
        run_id=run_id,
        actor="operator",
    )
    return run
