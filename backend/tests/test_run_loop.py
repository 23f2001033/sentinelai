"""End-to-end tests for the governed run loop.

The planner is scripted so the tests are deterministic and need no API key, but every
other layer is real: a real Chromium driving the real sandbox site, the real policy
engine, the real approval gate, and the real database.
"""

import asyncio
import functools
import http.server
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.enums import ApprovalStatus, RunStatus, StepStatus
from app.models import Agent, Approval, AuditEvent, PolicySet, Run, Step
from app.operator.actions import PlannedAction
from app.operator.planner import PlannerResult
from app.services.approvals import gate

DEMO_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "demo"

pytest.importorskip("playwright", reason="playwright not installed")
pytestmark = pytest.mark.asyncio(loop_scope="module")


TEST_POLICY = [
    {"id": "allow-navigate", "effect": "allow", "priority": 10,
     "when": {"field": "action.type", "op": "eq", "value": "navigate"}},
    {"id": "allow-read", "effect": "allow", "priority": 10,
     "when": {"field": "action.type", "op": "in", "value": ["read_page", "scroll"]}},
    {"id": "allow-click", "effect": "allow", "priority": 10,
     "when": {"field": "action.type", "op": "eq", "value": "click"}},
    {"id": "allow-safe-typing", "effect": "allow", "priority": 10,
     "when": {"all": [{"field": "action.type", "op": "eq", "value": "type"},
                      {"field": "action.is_sensitive", "op": "eq", "value": False}]}},
    {"id": "deny-sensitive", "effect": "deny", "priority": 100, "risk": 100,
     "reason": "Credential entry is never permitted.",
     "when": {"field": "action.is_sensitive", "op": "eq", "value": True}},
    {"id": "approve-submit", "effect": "require_approval", "priority": 50, "risk": 60,
     "reason": "Form submission writes data to an external system.",
     "when": {"field": "action.type", "op": "eq", "value": "submit"}},
]


@pytest.fixture(scope="module")
def demo_site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def agent_id():
    await init_db()
    async with SessionLocal() as session:
        policy = PolicySet(
            name="Run Loop Test Policy",
            default_effect="deny",
            rules=TEST_POLICY,
        )
        session.add(policy)
        await session.flush()
        agent = Agent(name="Loop Test Agent", role="tester", policy_set_id=policy.id)
        session.add(agent)
        await session.commit()
        return agent.id


class ScriptedPlanner:
    """Stands in for Claude, returning a fixed sequence of actions."""

    script: list = []

    def __init__(self, *args, **kwargs):
        self._remaining = list(type(self).script)

    async def plan(self, *, goal, observation, history):
        if not self._remaining:
            action = PlannedAction(rationale="Nothing left to do.", action="finish",
                                   params={"summary": "script exhausted"})
        else:
            action = self._remaining.pop(0)(observation)
        return PlannerResult(action=action, input_tokens=100, output_tokens=20,
                             cost_usd=0.001, model="scripted")


def find_ref(observation, needle):
    match = next(
        (e for e in observation.elements if needle.lower() in (e.name or "").lower()), None
    )
    assert match is not None, f"no element matching {needle!r} in {[e.name for e in observation.elements]}"
    return match


async def run_script(monkeypatch, agent_id, goal, start_url, script, auto_decide=None):
    ScriptedPlanner.script = script
    monkeypatch.setattr("app.services.runner.Planner", ScriptedPlanner)

    async with SessionLocal() as session:
        run = Run(agent_id=agent_id, goal=goal, start_url=start_url)
        session.add(run)
        await session.commit()
        run_id = run.id

    from app.services.runner import RunController

    resolver = asyncio.create_task(_auto_decide(run_id, auto_decide)) if auto_decide else None
    try:
        await asyncio.wait_for(RunController(run_id).run(), timeout=120)
    finally:
        if resolver:
            resolver.cancel()

    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        steps = list(
            await session.scalars(select(Step).where(Step.run_id == run_id).order_by(Step.index))
        )
        events = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id))
        )
        for step in steps:
            await session.refresh(step, ["decision", "approval"])
        return run, steps, events


async def _auto_decide(run_id: int, decision: ApprovalStatus):
    """Stands in for a human clicking approve or deny in the console."""
    while True:
        await asyncio.sleep(0.15)
        async with SessionLocal() as session:
            approval = await session.scalar(
                select(Approval).where(
                    Approval.run_id == run_id, Approval.status == str(ApprovalStatus.PENDING)
                )
            )
            if approval is None:
                continue
            approval.status = str(decision)
            approval.decided_by = "automated reviewer"
            approval.note = "decided by test"
            approval.decided_at = datetime.now(timezone.utc)
            await session.commit()
            approval_id = approval.id
        gate.resolve(approval_id)


class TestApprovedPath:
    async def test_gated_action_runs_only_after_a_human_approves(
        self, monkeypatch, agent_id, demo_site
    ):
        script = [
            lambda obs: PlannedAction(
                rationale="Fill in the requester's name.",
                action="type",
                params={"ref": find_ref(obs, "Your name").ref, "text": "Ada Lovelace"},
            ),
            lambda obs: PlannedAction(
                rationale="Send the meeting request to the vendor.",
                action="submit",
                params={"ref": find_ref(obs, "Send meeting request").ref},
            ),
            lambda obs: PlannedAction(
                rationale="The request was sent, so the goal is met.",
                action="finish",
                params={"summary": "Meeting request submitted."},
            ),
        ]
        run, steps, events = await run_script(
            monkeypatch, agent_id, "Book a meeting", f"{demo_site}/book.html",
            script, auto_decide=ApprovalStatus.APPROVED,
        )

        assert run.status == str(RunStatus.COMPLETED)
        by_action = {s.action_type: s for s in steps}

        assert by_action["type"].decision.effect == "allow"
        assert by_action["type"].status == str(StepStatus.SUCCEEDED)

        submit = by_action["submit"]
        assert submit.decision.effect == "require_approval"
        assert submit.approval.status == str(ApprovalStatus.APPROVED)
        assert submit.status == str(StepStatus.SUCCEEDED)

        kinds = [e.kind for e in events]
        assert "approval_requested" in kinds and "approval_resolved" in kinds
        assert "action_executed" in kinds

    async def test_the_gated_action_actually_changed_the_page(
        self, monkeypatch, agent_id, demo_site
    ):
        script = [
            lambda obs: PlannedAction(
                rationale="Send the meeting request.",
                action="submit",
                params={"ref": find_ref(obs, "Send meeting request").ref},
            ),
            lambda obs: PlannedAction(rationale="Done.", action="finish",
                                      params={"summary": "submitted"}),
        ]
        _, steps, _ = await run_script(
            monkeypatch, agent_id, "Submit the form", f"{demo_site}/book.html",
            script, auto_decide=ApprovalStatus.APPROVED,
        )
        submit = next(s for s in steps if s.action_type == "submit")
        assert "confirm.html" in submit.result["url"]


class TestDeniedPath:
    async def test_human_denial_stops_the_action_from_happening(
        self, monkeypatch, agent_id, demo_site
    ):
        script = [
            lambda obs: PlannedAction(
                rationale="Send the meeting request.",
                action="submit",
                params={"ref": find_ref(obs, "Send meeting request").ref},
            ),
            lambda obs: PlannedAction(
                rationale="A human blocked the submission, so stop and report it.",
                action="finish",
                params={"summary": "Blocked by reviewer."},
            ),
        ]
        run, steps, events = await run_script(
            monkeypatch, agent_id, "Try to submit", f"{demo_site}/book.html",
            script, auto_decide=ApprovalStatus.DENIED,
        )

        submit = next(s for s in steps if s.action_type == "submit")
        assert submit.approval.status == str(ApprovalStatus.DENIED)
        assert submit.status == str(StepStatus.DENIED)
        assert submit.result is None, "a denied action must never have executed"
        assert run.status == str(RunStatus.COMPLETED)
        assert any("Denied by" in e.message for e in events)

    async def test_policy_denial_blocks_without_asking_a_human(
        self, monkeypatch, agent_id, demo_site
    ):
        script = [
            lambda obs: PlannedAction(
                rationale="Enter the card number to pay the invoice.",
                action="type",
                params={"ref": find_ref(obs, "Card number").ref, "text": "4111111111111111"},
            ),
            lambda obs: PlannedAction(
                rationale="Card entry is not permitted, so stop.",
                action="finish",
                params={"summary": "Cannot pay: credential entry is blocked."},
            ),
        ]
        run, steps, events = await run_script(
            monkeypatch, agent_id, "Pay the invoice", f"{demo_site}/checkout.html", script
        )

        blocked = next(s for s in steps if s.action_type == "type")
        assert blocked.decision.effect == "deny"
        assert blocked.status == str(StepStatus.BLOCKED)
        assert blocked.result is None
        assert not any(a for a in [blocked.approval] if a), "a hard deny must not create an approval"
        assert any(e.kind == "action_blocked" for e in events)
        assert run.status == str(RunStatus.COMPLETED)

    async def test_sensitive_text_is_redacted_from_the_audit_trail(
        self, monkeypatch, agent_id, demo_site
    ):
        secret = "4111111111111111"
        script = [
            lambda obs: PlannedAction(
                rationale="Enter the card number.",
                action="type",
                params={"ref": find_ref(obs, "Card number").ref, "text": secret},
            ),
            lambda obs: PlannedAction(rationale="Stop.", action="finish",
                                      params={"summary": "blocked"}),
        ]
        _, _, events = await run_script(
            monkeypatch, agent_id, "Pay", f"{demo_site}/checkout.html", script
        )
        planned = next(e for e in events if e.kind == "step_planned" and "type" in str(e.payload))
        assert secret not in str(planned.payload)
        assert planned.payload["params"]["text"] == "[redacted]"


class TestLoopSafety:
    async def test_repeated_blocks_abort_the_run(self, monkeypatch, agent_id, demo_site):
        """An agent that keeps retrying a forbidden action must not spin forever."""
        attempt = lambda obs: PlannedAction(  # noqa: E731
            rationale="Try the card field again.",
            action="type",
            params={"ref": find_ref(obs, "Card number").ref, "text": "4111"},
        )
        run, _, _ = await run_script(
            monkeypatch, agent_id, "Keep trying", f"{demo_site}/checkout.html", [attempt] * 6
        )
        assert run.status == str(RunStatus.CANCELLED)
        assert "consecutive blocked" in run.summary

    async def test_spend_is_recorded_for_every_planner_call(
        self, monkeypatch, agent_id, demo_site
    ):
        script = [
            lambda obs: PlannedAction(rationale="Read it.", action="read_page", params={}),
            lambda obs: PlannedAction(rationale="Done.", action="finish",
                                      params={"summary": "read"}),
        ]
        run, _, events = await run_script(
            monkeypatch, agent_id, "Read the page", f"{demo_site}/index.html", script
        )
        llm_events = [e for e in events if e.kind == "llm_call"]
        assert len(llm_events) == 2
        assert all(e.payload["cost_usd"] > 0 for e in llm_events)
