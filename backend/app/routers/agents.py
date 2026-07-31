from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Agent, PolicySet
from ..schemas import AgentIn, AgentOut

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_agents(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(Agent).order_by(Agent.id)))


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentIn, session: AsyncSession = Depends(get_session)):
    if await session.get(PolicySet, payload.policy_set_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "policy set not found")
    if await session.scalar(select(Agent).where(Agent.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "an agent with that name already exists")

    agent = Agent(**payload.model_dump())
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: int, session: AsyncSession = Depends(get_session)):
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent
