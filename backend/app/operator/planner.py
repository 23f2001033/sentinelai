from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..config import Settings
from .actions import ACTION_SPECS, PlannedAction, action_catalogue
from .browser import PageObservation
from .providers import LLMClient, ProviderError, build_client, estimate_cost

SYSTEM_PROMPT = """You are the planning half of SentinelAI, a governed browser-operating agent.

You decide ONE next action at a time. You never execute anything yourself: every action you
propose is checked against a policy engine, and risky ones are held for a human to approve or
deny. Because a human reads your rationale to make that call, the rationale must be honest and
specific about what the action will actually do.

Available actions:
{catalogue}

Rules you must follow:
- Propose exactly one action per turn.
- Reference page elements only by the [eN] ref shown in the observation. Never invent a ref.
- Never propose typing into a field marked SENSITIVE. Those are credentials; a human must
  handle them. Propose `finish` and explain the blocker instead.
- If a previous step was denied by policy, do not retry it or look for a workaround. Either
  take a different legitimate route or `finish` and report the blocker.
- When the goal is met, or cannot be met without a blocked action, use `finish`.

Write the rationale for a colleague who is not watching your screen: say what you are about to
do and why it moves the goal forward, in one or two plain sentences. No jargon, no ref numbers.

Reply with a single JSON object and nothing else — no prose, no markdown fences. It must match
this JSON schema:

{schema}
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {
            "type": "string",
            "description": "One or two plain sentences explaining this step to a human reviewer.",
        },
        "action": {"type": "string", "enum": sorted(ACTION_SPECS)},
        "params": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Element ref such as e4."},
                "label": {"type": "string", "description": "Human-readable name of the target."},
                "url": {"type": "string"},
                "text": {"type": "string"},
                "value": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "summary": {"type": "string"},
                "amount_usd": {"type": "number"},
            },
        },
    },
    "required": ["rationale", "action", "params"],
}

FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class PlannerResult:
    action: PlannedAction
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


class PlannerError(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model reply that may be wrapped in prose or fences."""
    candidate = text.strip()
    fenced = FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise PlannerError(f"model did not return JSON: {text[:200]}")


class Planner:
    """Turns a page observation into one proposed action, via any configured provider."""

    def __init__(self, client: LLMClient | None = None, settings: Settings | None = None) -> None:
        try:
            self._client = client or build_client(settings)
        except ProviderError as exc:
            raise PlannerError(str(exc)) from exc
        self.model = self._client.model
        self.provider = self._client.provider

    def _system(self) -> str:
        return SYSTEM_PROMPT.format(
            catalogue=action_catalogue(), schema=json.dumps(RESPONSE_SCHEMA, indent=2)
        )

    def _user_turn(
        self, goal: str, observation: PageObservation, history: list[dict[str, Any]]
    ) -> str:
        if history:
            recent = "\n".join(
                f"{item['index']}. {item['action']} — {item.get('outcome', '')}"
                for item in history[-8:]
            )
        else:
            recent = "(nothing yet — this is the first step)"

        return (
            f"GOAL: {goal}\n\n"
            f"STEPS SO FAR:\n{recent}\n\n"
            f"CURRENT PAGE:\n{observation.render()}\n\n"
            "Propose the single next action as JSON."
        )

    async def plan(
        self, *, goal: str, observation: PageObservation, history: list[dict[str, Any]]
    ) -> PlannerResult:
        system = self._system()
        user = self._user_turn(goal, observation, history)
        input_tokens = output_tokens = 0
        last_error: str | None = None

        # Smaller open models occasionally wrap JSON in prose or miss a field; one
        # repair round costs far less than failing the whole run.
        for attempt in range(2):
            prompt = user if attempt == 0 else (
                f"{user}\n\nYour previous reply was rejected: {last_error}\n"
                "Reply with the corrected JSON object only."
            )
            try:
                completion = await self._client.complete(
                    system=system, user=prompt, schema=RESPONSE_SCHEMA
                )
            except ProviderError as exc:
                raise PlannerError(str(exc)) from exc
            except Exception as exc:
                raise PlannerError(f"{self.provider} request failed: {exc}") from exc

            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens

            try:
                action = PlannedAction.model_validate(extract_json(completion.text))
            except (PlannerError, ValidationError) as exc:
                last_error = str(exc)[:300]
                continue

            return PlannerResult(
                action=action,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
                model=self.model,
            )

        raise PlannerError(f"planner returned unusable output twice: {last_error}")
