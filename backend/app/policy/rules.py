from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..enums import Effect


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    MATCHES = "matches"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class Condition(BaseModel):
    """A leaf test (`field`/`op`/`value`) or a boolean group (`all`/`any`/`none`)."""

    model_config = ConfigDict(populate_by_name=True)

    field_path: str | None = Field(default=None, alias="field")
    op: Operator = Operator.EQ
    value: Any = None
    case_sensitive: bool = True

    all: list[Condition] | None = None
    any: list[Condition] | None = None
    none: list[Condition] | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> Self:
        groups = [g for g in (self.all, self.any, self.none) if g is not None]
        if self.field_path is not None and groups:
            raise ValueError("a condition cannot be both a leaf test and a boolean group")
        if self.field_path is None and not groups:
            raise ValueError("a condition needs either 'field' or one of 'all'/'any'/'none'")
        if len(groups) > 1:
            raise ValueError("use only one of 'all', 'any' or 'none' per condition")
        if groups and not groups[0]:
            raise ValueError("a boolean group needs at least one child condition")
        return self

    @property
    def is_leaf(self) -> bool:
        return self.field_path is not None


class Rule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    description: str = ""
    effect: Effect
    # Higher priority wins. Equal priority resolves to the most restrictive effect.
    priority: int = 0
    when: Condition | None = None
    reason: str = ""
    risk: int = Field(default=0, ge=0, le=100)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    def resolved_reason(self) -> str:
        return self.reason or self.description or f"matched rule '{self.id}'"


class PolicySpec(BaseModel):
    name: str
    description: str = ""
    default_effect: Effect = Effect.REQUIRE_APPROVAL
    default_reason: str = "No rule matched; falling back to the policy default."
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> Self:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id: {rule.id}")
            seen.add(rule.id)
        return self
