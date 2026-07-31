from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import SessionLocal
from ..enums import ApprovalStatus, AuditKind, Effect, RunStatus, StepStatus
from ..models import Agent, Approval, Decision, PolicySet, Run, SpendRecord, Step
from ..operator.actions import ActionValidationError, PlannedAction, validate_action
from ..operator.browser import BrowserOperator, BrowserOperatorError, PageObservation
from ..operator.planner import Planner, PlannerError
from ..policy import PolicyEngine, PolicySpec, build_context
from . import audit
from .approvals import gate
from .events import bus

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_SECONDS = 900
MAX_CONSECUTIVE_BLOCKS = 3
RUN_BUDGET_USD = 1.00


@dataclass
class RunState:
    # `steps_taken` counts actions that actually executed and drives the step budget;
    # `steps_planned` counts everything proposed, so blocked steps still get a unique
    # position in the timeline.
    steps_taken: int = 0
    steps_planned: int = 0
    spend_usd: float = 0.0
    approvals_granted: int = 0
    approvals_denied: int = 0
    blocked_actions: int = 0
    consecutive_blocks: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def budget_exhausted(self) -> bool:
        return self.spend_usd >= RUN_BUDGET_USD

    def as_context(self) -> dict[str, Any]:
        return {
            "steps_taken": self.steps_taken,
            "spend_usd": round(self.spend_usd, 6),
            "budget_usd": RUN_BUDGET_USD,
            "budget_exhausted": self.budget_exhausted,
            "approvals_granted": self.approvals_granted,
            "approvals_denied": self.approvals_denied,
            "blocked_actions": self.blocked_actions,
        }


class RunFinished(Exception):
    def __init__(self, status: RunStatus, summary: str) -> None:
        super().__init__(summary)
        self.status = status
        self.summary = summary


class RunController:
    """Executes one governed run: plan, check policy, gate, act, log — repeat.

    Nothing reaches the browser without passing `_gate`, which is the single place a
    policy decision is turned into permission to act.
    """

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.settings = get_settings()
        self.state = RunState()
        self.browser = BrowserOperator(
            headless=self.settings.browser_headless,
            no_sandbox=self.settings.browser_no_sandbox,
        )
        self._engine: PolicyEngine | None = None
        self._policy_meta: tuple[str, int] = ("", 1)
        self._agent_ctx: dict[str, Any] = {}
        self._goal = ""
        self._start_url = ""

    async def run(self) -> None:
        try:
            await self._load()
            await self._set_status(RunStatus.RUNNING)
            await self._log(AuditKind.RUN_STARTED, f"Run started: {self._goal}")
            await self.browser.start()
            await self._opening_navigation()
            await self._loop()
        except RunFinished as done:
            await self._finish(done.status, done.summary)
        except (PlannerError, BrowserOperatorError) as exc:
            await self._log(AuditKind.ERROR, str(exc))
            await self._finish(RunStatus.FAILED, str(exc))
        except Exception as exc:  # pragma: no cover - unexpected failures still audit
            logger.exception("run %s crashed", self.run_id)
            await self._log(AuditKind.ERROR, f"Unexpected failure: {exc}")
            await self._finish(RunStatus.FAILED, f"Unexpected failure: {exc}")
        finally:
            await self.browser.close()

    async def _load(self) -> None:
        async with SessionLocal() as session:
            run = await session.scalar(
                select(Run)
                .where(Run.id == self.run_id)
                .options(selectinload(Run.agent).selectinload(Agent.policy_set))
            )
            if run is None:
                raise RunFinished(RunStatus.FAILED, "run not found")
            policy: PolicySet = run.agent.policy_set
            spec = PolicySpec.model_validate(
                {
                    "name": policy.name,
                    "description": policy.description,
                    "default_effect": policy.default_effect,
                    "rules": policy.rules,
                }
            )
            self._engine = PolicyEngine(spec)
            self._policy_meta = (policy.name, policy.version)
            self._agent_ctx = {"name": run.agent.name, "role": run.agent.role}
            self._goal = run.goal
            self._start_url = run.start_url

    async def _loop(self) -> None:
        planner = Planner(settings=self.settings)

        while self.state.steps_taken < self.settings.max_steps_per_run:
            observation = await self.browser.observe()
            result = await planner.plan(
                goal=self._goal, observation=observation, history=self.state.history
            )
            self.state.spend_usd += result.cost_usd

            await self._record_spend(result)
            await self._process(result.action, observation)

        raise RunFinished(
            RunStatus.FAILED,
            f"Stopped after the {self.settings.max_steps_per_run}-step limit without finishing.",
        )

    async def _opening_navigation(self) -> None:
        if not self._start_url:
            return
        action = PlannedAction(
            rationale="Open the starting page the operator specified for this run.",
            action="navigate",
            params={"url": self._start_url, "label": "starting page"},
        )
        await self._process(action, PageObservation(), operator_directed=True)

    async def _process(
        self, planned: PlannedAction, observation: PageObservation, *, operator_directed: bool = False
    ) -> None:
        try:
            params = validate_action(planned.action, planned.params)
        except ActionValidationError as exc:
            await self._log(AuditKind.ERROR, f"Planner proposed an invalid action: {exc}")
            self.state.history.append(
                {
                    "index": self.state.steps_taken,
                    "action": planned.action,
                    "outcome": f"rejected before policy: {exc}",
                }
            )
            self.state.consecutive_blocks += 1
            self._guard_block_loop()
            return

        params = self._enrich_from_page(params, observation)
        step = await self._create_step(planned, params, observation)

        if planned.action == "finish":
            raise RunFinished(RunStatus.COMPLETED, str(params.get("summary", "")))

        evaluation = (
            PolicyEngine.preauthorized(
                "The run's starting page was specified by the operator, not chosen by the agent."
            )
            if operator_directed
            else self._evaluate(planned.action, params, observation)
        )
        await self._persist_decision(step.id, evaluation)
        await self._log(
            AuditKind.POLICY_EVALUATED,
            f"Policy decision: {evaluation.effect} — {evaluation.reason}",
            step_id=step.id,
            payload=evaluation.as_dict(),
        )

        if evaluation.effect is Effect.DENY:
            await self._mark_step(step.id, StepStatus.BLOCKED)
            await self._log(
                AuditKind.ACTION_BLOCKED,
                f"Blocked by policy: {evaluation.reason}",
                step_id=step.id,
                payload={"rule": evaluation.deciding_rule_id},
            )
            self.state.blocked_actions += 1
            self.state.consecutive_blocks += 1
            self._append_history(planned, f"BLOCKED by policy — {evaluation.reason}")
            self._guard_block_loop()
            return

        if evaluation.effect is Effect.REQUIRE_APPROVAL:
            approved = await self._await_human(step.id, evaluation.reason, planned, params)
            if not approved:
                self.state.consecutive_blocks += 1
                self._guard_block_loop()
                return

        self.state.consecutive_blocks = 0
        await self._execute(step.id, planned, params)

    def _enrich_from_page(
        self, params: dict[str, Any], observation: PageObservation
    ) -> dict[str, Any]:
        """Fill the label and sensitivity flag from what is actually on the page.

        The planner supplies a ref; trusting its own `label`/`is_sensitive` would let a
        mislabelled proposal dodge a rule, so both are re-derived from the live DOM.
        """
        ref = params.get("ref")
        if not ref:
            return params
        element = observation.element(str(ref))
        if element is None:
            return params
        enriched = dict(params)
        enriched["label"] = element.name or params.get("label", "")
        enriched["ref_role"] = element.type or element.role or element.tag
        if element.is_sensitive:
            enriched["is_sensitive"] = True
        return enriched

    def _evaluate(self, action: str, params: dict[str, Any], observation: PageObservation):
        assert self._engine is not None
        context = build_context(
            action_type=action,
            action_params=params,
            page_url=observation.url,
            page_title=observation.title,
            agent=self._agent_ctx,
            run={"goal": self._goal, "step_index": self.state.steps_taken},
            session=self.state.as_context(),
        )
        return self._engine.evaluate(context)

    async def _await_human(
        self, step_id: int, reason: str, planned: PlannedAction, params: dict[str, Any]
    ) -> bool:
        async with SessionLocal() as session:
            approval = Approval(step_id=step_id, run_id=self.run_id, requested_reason=reason)
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            approval_id = approval.id

        await self._mark_step(step_id, StepStatus.AWAITING_APPROVAL)
        await self._set_status(RunStatus.AWAITING_APPROVAL)
        gate.register(approval_id)
        await self._log(
            AuditKind.APPROVAL_REQUESTED,
            f"Waiting for a human: {reason}",
            step_id=step_id,
            payload={
                "approval_id": approval_id,
                "action": planned.action,
                "label": params.get("label", ""),
                "rationale": planned.rationale,
            },
        )

        resolved = await gate.wait(approval_id, APPROVAL_TIMEOUT_SECONDS)
        if not resolved:
            await self._mark_step(step_id, StepStatus.DENIED)
            await self._log(
                AuditKind.APPROVAL_RESOLVED,
                "Approval timed out; the action was not taken.",
                step_id=step_id,
            )
            raise RunFinished(RunStatus.CANCELLED, "No human responded to the approval request.")

        async with SessionLocal() as session:
            approval = await session.get(Approval, approval_id)
            status = ApprovalStatus(approval.status) if approval else ApprovalStatus.DENIED
            decided_by = approval.decided_by if approval else None
            note = approval.note if approval else ""

        await self._set_status(RunStatus.RUNNING)
        if status is ApprovalStatus.APPROVED:
            self.state.approvals_granted += 1
            await self._mark_step(step_id, StepStatus.APPROVED)
            await self._log(
                AuditKind.APPROVAL_RESOLVED,
                f"Approved by {decided_by or 'a reviewer'}.",
                step_id=step_id,
                actor=decided_by or "reviewer",
                payload={"note": note},
            )
            return True

        self.state.approvals_denied += 1
        await self._mark_step(step_id, StepStatus.DENIED)
        await self._log(
            AuditKind.APPROVAL_RESOLVED,
            f"Denied by {decided_by or 'a reviewer'}." + (f" Note: {note}" if note else ""),
            step_id=step_id,
            actor=decided_by or "reviewer",
            payload={"note": note},
        )
        self._append_history(planned, f"DENIED by a human reviewer — {note or 'no reason given'}")
        return False

    async def _execute(self, step_id: int, planned: PlannedAction, params: dict[str, Any]) -> None:
        await self._mark_step(step_id, StepStatus.EXECUTING)
        started = datetime.now(timezone.utc)
        try:
            result = await self.browser.execute(planned.action, params)
            error = None
            status = StepStatus.SUCCEEDED
        except Exception as exc:
            result, error, status = {}, str(exc), StepStatus.FAILED

        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        async with SessionLocal() as session:
            step = await session.get(Step, step_id)
            step.status = str(status)
            step.result = result
            step.error = error
            step.duration_ms = duration_ms
            step.page_url = self.browser.page.url if self.browser._page else step.page_url
            await session.commit()

        self.state.steps_taken += 1
        outcome = f"succeeded ({result})" if error is None else f"failed ({error})"
        self._append_history(planned, outcome)
        await self._log(
            AuditKind.ACTION_EXECUTED,
            f"{planned.action}: {outcome}",
            step_id=step_id,
            payload={"result": result, "error": error, "duration_ms": duration_ms},
        )

    def _append_history(self, planned: PlannedAction, outcome: str) -> None:
        self.state.history.append(
            {
                "index": len(self.state.history) + 1,
                "action": f"{planned.action} {planned.params.get('label') or planned.params.get('url') or ''}".strip(),
                "outcome": outcome,
            }
        )

    def _guard_block_loop(self) -> None:
        if self.state.consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
            raise RunFinished(
                RunStatus.CANCELLED,
                f"Stopped after {MAX_CONSECUTIVE_BLOCKS} consecutive blocked or denied actions.",
            )

    async def _create_step(
        self, planned: PlannedAction, params: dict[str, Any], observation: PageObservation
    ) -> Step:
        self.state.steps_planned += 1
        async with SessionLocal() as session:
            step = Step(
                run_id=self.run_id,
                index=self.state.steps_planned,
                rationale=planned.rationale,
                action_type=planned.action,
                action_params=params,
                page_url=observation.url,
            )
            session.add(step)
            await session.commit()
            await session.refresh(step)

        await self._log(
            AuditKind.STEP_PLANNED,
            planned.rationale or f"Planned {planned.action}",
            step_id=step.id,
            payload={"action": planned.action, "params": _redact(params)},
        )
        return step

    async def _persist_decision(self, step_id: int, evaluation) -> None:
        name, version = self._policy_meta
        async with SessionLocal() as session:
            session.add(
                Decision(
                    step_id=step_id,
                    effect=str(evaluation.effect),
                    reason=evaluation.reason,
                    matched_rules=[m.as_dict() for m in evaluation.matches],
                    used_default=evaluation.used_default,
                    policy_set_name=name,
                    policy_version=version,
                )
            )
            await session.commit()

    async def _record_spend(self, result) -> None:
        async with SessionLocal() as session:
            session.add(
                SpendRecord(
                    run_id=self.run_id,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                    purpose="planner",
                )
            )
            await session.commit()

        await self._log(
            AuditKind.LLM_CALL,
            f"Planner call: {result.input_tokens} in / {result.output_tokens} out "
            f"(${result.cost_usd:.4f})",
            payload={
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "run_total_usd": round(self.state.spend_usd, 6),
            },
        )

    async def _mark_step(self, step_id: int, status: StepStatus) -> None:
        async with SessionLocal() as session:
            step = await session.get(Step, step_id)
            step.status = str(status)
            await session.commit()
        await bus.publish(
            self.run_id, {"type": "step_status", "step_id": step_id, "status": str(status)}
        )

    async def _set_status(self, status: RunStatus) -> None:
        async with SessionLocal() as session:
            run = await session.get(Run, self.run_id)
            run.status = str(status)
            await session.commit()
        await bus.publish(
            self.run_id, {"type": "run_status", "run_id": self.run_id, "status": str(status)}
        )

    async def _finish(self, status: RunStatus, summary: str) -> None:
        async with SessionLocal() as session:
            run = await session.get(Run, self.run_id)
            if run is None:
                return
            run.status = str(status)
            run.summary = summary
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()

        await self._log(
            AuditKind.RUN_FINISHED,
            f"Run {status}: {summary}",
            payload={"status": str(status), "spend_usd": round(self.state.spend_usd, 6)},
        )
        await bus.publish(
            self.run_id, {"type": "run_status", "run_id": self.run_id, "status": str(status)}
        )

    async def _log(
        self,
        kind: AuditKind,
        message: str,
        *,
        step_id: int | None = None,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> None:
        async with SessionLocal() as session:
            await audit.record(
                session,
                kind=kind,
                message=message,
                run_id=self.run_id,
                step_id=step_id,
                payload=payload,
                actor=actor,
            )


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("is_sensitive") and "text" in params:
        return {**params, "text": "[redacted]"}
    return params


async def start_run(run_id: int) -> None:
    await RunController(run_id).run()
