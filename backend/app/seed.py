from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, PolicySet
from .policy import load_default_policy


async def seed_defaults(session: AsyncSession) -> None:
    """Install the baseline policy and a starter agent on an empty database."""
    if await session.scalar(select(PolicySet.id).limit(1)) is not None:
        return

    spec = load_default_policy()
    policy = PolicySet(
        name=spec.name,
        description=spec.description,
        default_effect=str(spec.default_effect),
        rules=[
            rule.model_dump(mode="json", exclude_none=True, by_alias=True) for rule in spec.rules
        ],
    )
    session.add(policy)
    await session.flush()

    session.add(
        Agent(
            name="Procurement Assistant",
            role="Vendor coordination",
            description=(
                "Operates the procurement portal to look up vendors and arrange meetings. "
                "Every write, send or payment step is gated by the baseline policy."
            ),
            policy_set_id=policy.id,
        )
    )
    await session.commit()
