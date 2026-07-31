from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..enums import ApprovalStatus
from ..models import Approval, Run, Step
from ..schemas import ApprovalDecisionIn, ApprovalOut, PendingApprovalOut
from ..services.approvals import gate

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[PendingApprovalOut])
async def list_approvals(
    status_filter: ApprovalStatus | None = None, session: AsyncSession = Depends(get_session)
):
    query = (
        select(Approval)
        .options(selectinload(Approval.step).selectinload(Step.decision))
        .order_by(Approval.id.desc())
    )
    if status_filter is not None:
        query = query.where(Approval.status == str(status_filter))

    approvals = list(await session.scalars(query))
    run_goals = {
        run.id: run.goal
        for run in await session.scalars(
            select(Run).where(Run.id.in_({a.run_id for a in approvals} or {0}))
        )
    }

    out = []
    for approval in approvals:
        step = approval.step
        decision = step.decision if step else None
        risk = 0
        if decision and decision.matched_rules:
            risk = max((m.get("risk", 0) for m in decision.matched_rules), default=0)
        out.append(
            PendingApprovalOut(
                **ApprovalOut.model_validate(approval).model_dump(),
                run_goal=run_goals.get(approval.run_id, ""),
                action_type=step.action_type if step else "",
                action_label=str(step.action_params.get("label", "")) if step else "",
                rationale=step.rationale if step else "",
                risk_score=risk,
            )
        )
    return out


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
async def decide(
    approval_id: int, payload: ApprovalDecisionIn, session: AsyncSession = Depends(get_session)
):
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    if approval.status != str(ApprovalStatus.PENDING):
        raise HTTPException(status.HTTP_409_CONFLICT, "this approval has already been decided")
    if payload.decision is ApprovalStatus.PENDING:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "decision must be approve or deny")

    approval.status = str(payload.decision)
    approval.decided_by = payload.decided_by
    approval.note = payload.note
    approval.decided_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(approval)

    # The waiting run reads the persisted row, so commit before releasing the gate.
    gate.resolve(approval_id)
    return approval
