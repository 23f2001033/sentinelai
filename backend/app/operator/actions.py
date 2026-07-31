from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

SENSITIVE_PATTERN = re.compile(
    r"password|passcode|\bpin\b|cvv|cvc|card\s*number|credit\s*card|"
    r"security\s*code|ssn|social\s*security|api[\s_-]?key|secret|token|"
    r"routing\s*number|account\s*number|iban",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    needs_element: bool = False


ACTION_SPECS: dict[str, ActionSpec] = {
    spec.name: spec
    for spec in [
        ActionSpec("read_page", "Re-read the current page without changing anything."),
        ActionSpec("navigate", "Load a different URL.", required=("url",)),
        ActionSpec("click", "Click a link or button.", required=("ref",), needs_element=True),
        ActionSpec(
            "type",
            "Type text into an input field.",
            required=("ref", "text"),
            optional=("is_sensitive",),
            needs_element=True,
        ),
        ActionSpec(
            "select",
            "Choose an option from a dropdown.",
            required=("ref", "value"),
            needs_element=True,
        ),
        ActionSpec(
            "submit",
            "Submit a form, writing data to the site.",
            required=("ref",),
            needs_element=True,
        ),
        ActionSpec("scroll", "Scroll the page.", optional=("direction",)),
        ActionSpec("download", "Download a file.", required=("url",)),
        ActionSpec("finish", "Stop; the goal is met or cannot be met.", required=("summary",)),
    ]
}


class PlannedAction(BaseModel):
    """One step the planner wants to take, before any policy check has run."""

    rationale: str = Field(default="", description="Plain-English reason for this step.")
    action: str
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        return str(self.params.get("label") or "")


class ActionValidationError(ValueError):
    pass


def is_sensitive_label(*candidates: str | None) -> bool:
    return any(SENSITIVE_PATTERN.search(c) for c in candidates if c)


def validate_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Check an action against its spec and normalise its parameters.

    Sensitivity is decided here rather than trusted from the planner, so a model that
    omits or lies about `is_sensitive` still cannot slip a credential past the policy.
    """
    spec = ACTION_SPECS.get(action)
    if spec is None:
        raise ActionValidationError(
            f"unknown action '{action}'; expected one of {sorted(ACTION_SPECS)}"
        )

    missing = [key for key in spec.required if not str(params.get(key, "")).strip()]
    if missing:
        raise ActionValidationError(f"action '{action}' is missing required params: {missing}")

    normalised = dict(params)
    if action in {"navigate", "download"}:
        url = str(normalised["url"]).strip()
        scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", url)
        if scheme is None:
            url = f"https://{url}"
        elif scheme.group(1).lower() not in {"http", "https"}:
            # file://, data:, javascript: and friends would let the agent read local
            # files or run script outside the action surface.
            raise ActionValidationError(
                f"action '{action}' only accepts http/https URLs, got '{scheme.group(1)}:'"
            )
        normalised["url"] = url

    if action in {"type", "select"}:
        detected = is_sensitive_label(
            normalised.get("label"), normalised.get("field_name"), normalised.get("ref_role")
        )
        normalised["is_sensitive"] = bool(normalised.get("is_sensitive")) or detected
    else:
        normalised.setdefault("is_sensitive", False)

    return normalised


def action_catalogue() -> str:
    lines = []
    for spec in ACTION_SPECS.values():
        req = f" required: {', '.join(spec.required)}" if spec.required else ""
        opt = f" optional: {', '.join(spec.optional)}" if spec.optional else ""
        lines.append(f"- {spec.name}: {spec.description}{req}{opt}")
    return "\n".join(lines)
