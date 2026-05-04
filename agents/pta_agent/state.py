from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import TaskSpec


CONFIRMATION_KEYS = {
    "confirmation_id",
    "payment_confirmation_id",
    "return_id",
    "label_id",
}


@dataclass
class StateManager:
    task: TaskSpec
    resources: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    failed_attempts: list[dict[str, Any]] = field(default_factory=list)
    policy_violations: list[dict[str, Any]] = field(default_factory=list)
    final_output: dict[str, Any] | None = None

    def add_resource(self, uri: str, payload: Any) -> None:
        self.resources[uri] = payload

    def add_tool_result(self, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
        self.tool_results.append({"tool_name": tool_name, "arguments": arguments, "result": result})

    def add_failed_attempt(self, event: dict[str, Any]) -> None:
        self.failed_attempts.append(event)

    def add_policy_violation(self, event: dict[str, Any]) -> None:
        self.policy_violations.append(event)

    def has_resource(self, uri: str) -> bool:
        return uri in self.resources

    def get_resource(self, uri: str, default: Any = None) -> Any:
        return self.resources.get(uri, default)

    def get_tool_results(self, tool_name: str | None = None) -> list[dict[str, Any]]:
        if tool_name is None:
            return list(self.tool_results)
        return [item for item in self.tool_results if item["tool_name"] == tool_name]

    def has_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        return any(item["tool_name"] == tool_name and item["arguments"] == arguments for item in self.tool_results)

    def confirmation_values(self) -> set[str]:
        values: set[str] = set()
        for item in self.tool_results:
            collect_confirmation_values(item.get("result"), values)
        return values

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task.task_id,
            "resources": self.resources,
            "tool_results": self.tool_results,
            "failed_attempts": self.failed_attempts,
            "policy_violations": self.policy_violations,
            "final_output": self.final_output,
        }


def collect_confirmation_values(value: Any, values: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in CONFIRMATION_KEYS or "confirmation" in key:
                if isinstance(child, str):
                    values.add(child)
                elif isinstance(child, list):
                    values.update(item for item in child if isinstance(item, str))
            collect_confirmation_values(child, values)
    elif isinstance(value, list):
        for item in value:
            collect_confirmation_values(item, values)
