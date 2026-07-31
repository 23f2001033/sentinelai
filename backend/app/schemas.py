from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import ApprovalStatus, Effect
from .policy.rules import Rule


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PolicySetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    default_effect: Effect = Effect.REQUIRE_APPROVAL
    rules: list[Rule] = Field(default_factory=list)


class PolicySetOut(ORMModel):
    id: int
    name: str
    description: str
    default_effect: str
    rules: list[dict[str, Any]]
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SimulationIn(BaseModel):
    action_type: str
    action_params: dict[str, Any] = Field(default_factory=dict)
    page_url: str = ""
    page_title: str = ""
    session: dict[str, Any] = Field(default_factory=dict)


class SimulationOut(BaseModel):
    effect: str
    reason: str
    used_default: bool
    risk_score: int
    deciding_rule_id: str | None
    matches: list[dict[str, Any]]
    warnings: list[str]
    context: dict[str, Any]


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = ""
    description: str = ""
    policy_set_id: int


class AgentOut(ORMModel):
    id: int
    name: str
    role: str
    description: str
    policy_set_id: int
    created_at: datetime


class RunIn(BaseModel):
    agent_id: int
    goal: str = Field(min_length=3)
    start_url: str = ""
    requested_by: str = "operator"


class DecisionOut(ORMModel):
    effect: str
    reason: str
    matched_rules: list[dict[str, Any]]
    used_default: bool
    policy_set_name: str
    policy_version: int


class ApprovalOut(ORMModel):
    id: int
    step_id: int
    run_id: int
    status: str
    requested_reason: str
    decided_by: str | None
    note: str
    created_at: datetime
    decided_at: datetime | None


class StepOut(ORMModel):
    id: int
    index: int
    rationale: str
    action_type: str
    action_params: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    error: str | None
    duration_ms: int | None
    page_url: str
    created_at: datetime
    decision: DecisionOut | None = None
    approval: ApprovalOut | None = None


class RunOut(ORMModel):
    id: int
    agent_id: int
    goal: str
    start_url: str
    requested_by: str
    status: str
    summary: str
    created_at: datetime
    finished_at: datetime | None


class RunDetailOut(RunOut):
    steps: list[StepOut] = Field(default_factory=list)


class ApprovalDecisionIn(BaseModel):
    decision: ApprovalStatus
    decided_by: str = "reviewer"
    note: str = ""


class AuditEventOut(ORMModel):
    id: int
    run_id: int | None
    step_id: int | None
    kind: str
    message: str
    payload: dict[str, Any]
    actor: str
    created_at: datetime


class SpendSummaryOut(BaseModel):
    total_usd: float
    total_input_tokens: int
    total_output_tokens: int
    calls: int
    by_run: list[dict[str, Any]]


class PendingApprovalOut(ApprovalOut):
    run_goal: str = ""
    action_type: str = ""
    action_label: str = ""
    rationale: str = ""
    risk_score: int = 0
