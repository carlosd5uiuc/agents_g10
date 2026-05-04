from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ActionType(StrEnum):
    READ_RESOURCE = "read_resource"
    CALL_TOOL = "call_tool"
    FINALIZE = "finalize"
    ASK_CLARIFICATION = "ask_clarification"
    STOP = "stop"


class RunStatus(StrEnum):
    SUCCESS = "success"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED_CONSTRAINTS = "failed_constraints"
    TOOL_ERROR = "tool_error"
    MODEL_INVALID_OUTPUT = "model_invalid_output"
    VERIFICATION_FAILED = "verification_failed"
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"
    UNSUPPORTED_TASK = "unsupported_task"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REPAIR = "repair"
    CLARIFY = "clarify"
    STOP = "stop"


SUPPORTED_ACTIONS = {action.value for action in ActionType}


@dataclass(frozen=True)
class ActionProposal:
    action: ActionType
    resource_uri: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    final_output: dict[str, Any] | None = None
    message: str | None = None
    reason: str | None = None
    status: RunStatus | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "ActionProposal":
        if not isinstance(raw, dict):
            raise ValueError("Action proposal must be a JSON object.")

        action_value = raw.get("action")
        if action_value not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported action: {action_value!r}.")

        action = ActionType(action_value)
        arguments = raw.get("arguments") or raw.get("tool_args") or raw.get("args") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Action arguments must be an object.")

        status = raw.get("status")
        parsed_status = RunStatus(status) if status else None

        proposal = cls(
            action=action,
            resource_uri=raw.get("resource_uri"),
            tool_name=raw.get("tool_name"),
            arguments=arguments,
            final_output=raw.get("final_output") or raw.get("output"),
            message=raw.get("message"),
            reason=raw.get("reason"),
            status=parsed_status,
        )
        proposal.validate_shape()
        return proposal

    def validate_shape(self) -> None:
        if self.action == ActionType.READ_RESOURCE and not self.resource_uri:
            raise ValueError("read_resource requires resource_uri.")
        if self.action == ActionType.CALL_TOOL and not self.tool_name:
            raise ValueError("call_tool requires tool_name.")
        if self.action == ActionType.FINALIZE and not isinstance(self.final_output, dict):
            raise ValueError("finalize requires final_output object.")
        if self.action == ActionType.ASK_CLARIFICATION and not self.message:
            raise ValueError("ask_clarification requires message.")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.action.value,
            "arguments": self.arguments,
        }
        if self.resource_uri:
            data["resource_uri"] = self.resource_uri
        if self.tool_name:
            data["tool_name"] = self.tool_name
        if self.final_output is not None:
            data["final_output"] = self.final_output
        if self.message:
            data["message"] = self.message
        if self.reason:
            data["reason"] = self.reason
        if self.status:
            data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def allow(cls, reason: str = "allowed") -> "PolicyDecision":
        return cls(PolicyOutcome.ALLOW, [reason])

    @classmethod
    def deny(cls, *reasons: str) -> "PolicyDecision":
        return cls(PolicyOutcome.DENY, list(reasons) or ["denied"])

    @classmethod
    def repair(cls, *reasons: str) -> "PolicyDecision":
        return cls(PolicyOutcome.REPAIR, list(reasons) or ["repair required"])

    @classmethod
    def clarify(cls, *reasons: str) -> "PolicyDecision":
        return cls(PolicyOutcome.CLARIFY, list(reasons) or ["clarification required"])

    @classmethod
    def stop(cls, *reasons: str) -> "PolicyDecision":
        return cls(PolicyOutcome.STOP, list(reasons) or ["stop"])

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome.value, "reasons": self.reasons}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt: str
    hard_constraints: list[str]
    preferences: list[str]
    output_structure: dict[str, Any]
    resource_uris: list[str]
    tool_names: list[str]
    tool_schemas: list[dict[str, Any]]
    irreversible_tools: set[str]
    behavior_checklist: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunConfig:
    task_id: str
    provider: str = "mock"
    repo_root: Path = Path.cwd()
    output_root: Path | None = None
    max_steps: int = 30
    server_script: Path | None = None
    task_delay_seconds: float = 0.0
    session_id: str | None = None
