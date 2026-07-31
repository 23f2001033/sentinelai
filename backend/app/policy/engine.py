from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..enums import Effect
from .rules import Condition, Operator, PolicySpec, Rule

MISSING = object()

# Used only to break ties between rules of equal priority.
_SEVERITY: dict[Effect, int] = {
    Effect.ALLOW: 0,
    Effect.REQUIRE_APPROVAL: 1,
    Effect.DENY: 2,
}


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    effect: Effect
    priority: int
    reason: str
    risk: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "effect": str(self.effect),
            "priority": self.priority,
            "reason": self.reason,
            "risk": self.risk,
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    effect: Effect
    reason: str
    matches: list[RuleMatch] = field(default_factory=list)
    used_default: bool = False
    risk_score: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def deciding_rule_id(self) -> str | None:
        return self.matches[0].rule_id if self.matches else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect": str(self.effect),
            "reason": self.reason,
            "used_default": self.used_default,
            "risk_score": self.risk_score,
            "deciding_rule_id": self.deciding_rule_id,
            "matches": [m.as_dict() for m in self.matches],
            "warnings": list(self.warnings),
        }


def resolve_path(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


def _norm(value: Any, case_sensitive: bool) -> Any:
    if not case_sensitive and isinstance(value, str):
        return value.casefold()
    return value


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


class PolicyEngine:
    """Evaluates an action against a policy set and returns a governance decision.

    Resolution order: highest `priority` among matching rules wins. Rules that tie on
    priority resolve to the most restrictive effect (deny > require_approval > allow),
    which keeps an accidental ordering change from silently widening access.
    """

    def __init__(self, spec: PolicySpec) -> None:
        self.spec = spec

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyEngine:
        return cls(PolicySpec.model_validate(data))

    @staticmethod
    def preauthorized(reason: str) -> PolicyEvaluation:
        """A decision for actions a human already authorised out-of-band.

        Used for the operator-supplied starting URL: choosing where a run begins is a
        human decision made when the run was created, not a policy question for the
        agent's own choices. It still gets a normal decision row for the audit trail.
        """
        return PolicyEvaluation(effect=Effect.ALLOW, reason=reason, matches=[], used_default=False)

    def evaluate(self, context: dict[str, Any]) -> PolicyEvaluation:
        warnings: list[str] = []
        matches: list[tuple[int, Rule]] = []

        for index, rule in enumerate(self.spec.rules):
            if not rule.enabled:
                continue
            if rule.when is None or self._matches(rule.when, context, warnings):
                matches.append((index, rule))

        if not matches:
            return PolicyEvaluation(
                effect=self.spec.default_effect,
                reason=self.spec.default_reason,
                used_default=True,
                warnings=warnings,
            )

        matches.sort(key=lambda pair: (-pair[1].priority, -_SEVERITY[pair[1].effect], pair[0]))
        ordered = [
            RuleMatch(
                rule_id=rule.id,
                effect=rule.effect,
                priority=rule.priority,
                reason=rule.resolved_reason(),
                risk=rule.risk,
            )
            for _, rule in matches
        ]
        winner = ordered[0]
        return PolicyEvaluation(
            effect=winner.effect,
            reason=winner.reason,
            matches=ordered,
            used_default=False,
            risk_score=max(m.risk for m in ordered),
            warnings=warnings,
        )

    def _matches(self, condition: Condition, context: dict[str, Any], warnings: list[str]) -> bool:
        if condition.all is not None:
            return all(self._matches(c, context, warnings) for c in condition.all)
        if condition.any is not None:
            return any(self._matches(c, context, warnings) for c in condition.any)
        if condition.none is not None:
            return not any(self._matches(c, context, warnings) for c in condition.none)
        return self._test_leaf(condition, context, warnings)

    def _test_leaf(
        self, condition: Condition, context: dict[str, Any], warnings: list[str]
    ) -> bool:
        assert condition.field_path is not None
        actual = resolve_path(context, condition.field_path)
        op = condition.op

        if op is Operator.EXISTS:
            return actual is not MISSING
        if op is Operator.NOT_EXISTS:
            return actual is MISSING
        if actual is MISSING:
            return False

        cs = condition.case_sensitive
        left = _norm(actual, cs)
        right = _norm(condition.value, cs)

        match op:
            case Operator.EQ:
                return left == right
            case Operator.NEQ:
                return left != right
            case Operator.GT | Operator.GTE | Operator.LT | Operator.LTE:
                a, b = _as_number(actual), _as_number(condition.value)
                if a is None or b is None:
                    warnings.append(
                        f"{condition.field_path}: '{op}' needs numeric operands, got "
                        f"{type(actual).__name__} and {type(condition.value).__name__}"
                    )
                    return False
                return {
                    Operator.GT: a > b,
                    Operator.GTE: a >= b,
                    Operator.LT: a < b,
                    Operator.LTE: a <= b,
                }[op]
            case Operator.IN | Operator.NOT_IN:
                haystack = condition.value
                if not isinstance(haystack, (list, tuple, set)):
                    warnings.append(f"{condition.field_path}: '{op}' needs a list value")
                    return False
                found = any(left == _norm(item, cs) for item in haystack)
                return found if op is Operator.IN else not found
            case Operator.CONTAINS | Operator.NOT_CONTAINS:
                if isinstance(left, str):
                    found = isinstance(right, str) and right in left
                elif isinstance(left, (list, tuple, set)):
                    found = any(_norm(item, cs) == right for item in left)
                else:
                    warnings.append(
                        f"{condition.field_path}: '{op}' needs a string or list operand"
                    )
                    return False
                return found if op is Operator.CONTAINS else not found
            case Operator.STARTSWITH | Operator.ENDSWITH:
                if not isinstance(left, str) or not isinstance(right, str):
                    warnings.append(f"{condition.field_path}: '{op}' needs string operands")
                    return False
                return left.startswith(right) if op is Operator.STARTSWITH else left.endswith(right)
            case Operator.MATCHES:
                if not isinstance(actual, str) or not isinstance(condition.value, str):
                    warnings.append(f"{condition.field_path}: 'matches' needs string operands")
                    return False
                flags = 0 if cs else re.IGNORECASE
                try:
                    return re.search(condition.value, actual, flags) is not None
                except re.error as exc:
                    warnings.append(f"{condition.field_path}: invalid regex ({exc})")
                    return False

        return False
