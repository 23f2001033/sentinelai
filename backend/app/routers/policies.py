from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import PolicySet
from ..policy import PolicyEngine, PolicySpec, build_context
from ..schemas import PolicySetIn, PolicySetOut, SimulationIn, SimulationOut

router = APIRouter(prefix="/api/policies", tags=["policies"])


async def _get(session: AsyncSession, policy_id: int) -> PolicySet:
    policy = await session.get(PolicySet, policy_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "policy set not found")
    return policy


@router.get("", response_model=list[PolicySetOut])
async def list_policies(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(PolicySet).order_by(PolicySet.id))
    return list(result)


@router.get("/{policy_id}", response_model=PolicySetOut)
async def get_policy(policy_id: int, session: AsyncSession = Depends(get_session)):
    return await _get(session, policy_id)


@router.post("", response_model=PolicySetOut, status_code=status.HTTP_201_CREATED)
async def create_policy(payload: PolicySetIn, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(select(PolicySet).where(PolicySet.name == payload.name))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a policy set with that name already exists")
    policy = PolicySet(
        name=payload.name,
        description=payload.description,
        default_effect=str(payload.default_effect),
        rules=[r.model_dump(mode="json", exclude_none=True, by_alias=True) for r in payload.rules],
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


@router.put("/{policy_id}", response_model=PolicySetOut)
async def update_policy(
    policy_id: int, payload: PolicySetIn, session: AsyncSession = Depends(get_session)
):
    policy = await _get(session, policy_id)
    policy.name = payload.name
    policy.description = payload.description
    policy.default_effect = str(payload.default_effect)
    policy.rules = [
        r.model_dump(mode="json", exclude_none=True, by_alias=True) for r in payload.rules
    ]
    policy.version += 1
    await session.commit()
    await session.refresh(policy)
    return policy


@router.post("/{policy_id}/simulate", response_model=SimulationOut)
async def simulate(
    policy_id: int, payload: SimulationIn, session: AsyncSession = Depends(get_session)
):
    """Dry-run an action against a policy without touching a browser."""
    policy = await _get(session, policy_id)
    try:
        spec = PolicySpec.model_validate(
            {
                "name": policy.name,
                "default_effect": policy.default_effect,
                "rules": policy.rules,
            }
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid policy: {exc}") from exc

    context = build_context(
        action_type=payload.action_type,
        action_params=payload.action_params,
        page_url=payload.page_url,
        page_title=payload.page_title,
        session=payload.session,
    )
    evaluation = PolicyEngine(spec).evaluate(context)
    return SimulationOut(**evaluation.as_dict(), context=context)
