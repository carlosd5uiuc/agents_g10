from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import TaskSpec


TASK_RUNTIME: dict[str, dict[str, Any]] = {
    "task_01": {
        "resource_uris": ["transportation://list"],
        "tool_names": ["create_travel_arrangement", "create_calendar_entry"],
        "irreversible_tools": {"create_travel_arrangement", "create_calendar_entry"},
    },
    "task_02": {
        "resource_uris": ["repair://options"],
        "tool_names": ["set_up_repair_appointment"],
        "irreversible_tools": {"set_up_repair_appointment"},
    },
    "task_03": {
        "resource_uris": ["catering://options"],
        "tool_names": ["set_catering_appointment", "send_invitations"],
        "irreversible_tools": {"set_catering_appointment", "send_invitations"},
    },
    "task_04": {
        "prompt": "Schedule a dermatologist appointment for eczema support on Friday after 3 pm with copay at most $50.",
        "hard_constraints": ["Dermatologist", "Eczema-supported", "Copay <= $50", "Friday after 3 pm"],
        "preferences": [],
        "output_structure": {"success": "bool", "appointment_confirmation": {"confirmation_id": "string"}},
        "resource_uris": ["doctor://list"],
        "tool_names": ["set_up_doctor_appointment", "create_calendar_entry"],
        "irreversible_tools": {"set_up_doctor_appointment", "create_calendar_entry"},
        "behavior_checklist": [
            "Read doctor://list before choosing a provider.",
            "For the slot Friday,16, use calendar datetime 2026-05-08T16:00:00.",
            "Do not ask the user for the Friday date; this benchmark encodes the current week.",
            "Create a MEDICAL calendar entry after the doctor appointment tool succeeds.",
        ],
    },
    "task_05": {
        "prompt": "Troubleshoot a washer that is not draining and recommend a repair service under distance and cost constraints.",
        "hard_constraints": ["Diagnose washer drain issue", "Repair service < 5 miles", "Estimate <= $200"],
        "preferences": [],
        "output_structure": {"success": "bool", "recommendation": "object"},
        "resource_uris": ["troubleshoot://guide", "troubleshoot://repair"],
        "tool_names": [],
        "irreversible_tools": set(),
        "behavior_checklist": [
            "Use top-level recommended_steps as the canonical output field.",
            "repair_recommendation should contain only service_name, distance_miles, and estimated_cost.",
        ],
    },
    "task_06": {
        "prompt": "Identify unsettled household bills and schedule reminders or payment-plan entries.",
        "hard_constraints": ["Ignore settled bills", "Create entries for pending bills"],
        "preferences": [],
        "output_structure": {"success": "bool", "scheduled_payments": "list[object]"},
        "resource_uris": ["household-bills://list"],
        "tool_names": ["schedule_payment"],
        "irreversible_tools": {"schedule_payment"},
        "behavior_checklist": [
            "pending_bills must include only bills where settled is false.",
            "scheduled_payments must correspond exactly to the unsettled bills that were scheduled.",
            "Do not include settled bills in pending_bills, even as context.",
        ],
    },
    "task_07": {
        "prompt": "Create a weekly exercise routine with three strength and three cardio sessions.",
        "hard_constraints": ["3 strength sessions", "3 cardio sessions", "Calendar updated"],
        "preferences": ["Pair strength and cardio on the same day when possible"],
        "output_structure": {"success": "bool", "scheduled_activities": "list[object]"},
        "resource_uris": ["workout-sessions://list"],
        "tool_names": ["create_calendar_entry"],
        "irreversible_tools": {"create_calendar_entry"},
    },
    "task_08": {
        "prompt": "Generate an expense reduction report without cutting priority categories.",
        "hard_constraints": ["Use observed expenses", "Do not cut priority categories", "Provide at least one suggestion"],
        "preferences": [],
        "output_structure": {"success": "bool", "report": "string"},
        "resource_uris": ["expenses://list"],
        "tool_names": ["generate_report"],
        "irreversible_tools": set(),
    },
    "task_09": {
        "prompt": "Create a free drop-off return refunded to the original payment method and add the deadline to calendar.",
        "hard_constraints": ["Free return", "Drop-off", "Original payment refund", "Calendar updated"],
        "preferences": [],
        "output_structure": {"success": "bool", "return_confirmation": {"return_id": "string", "label_id": "string"}},
        "resource_uris": ["online-purchase://return_options"],
        "tool_names": ["create_return", "create_calendar_entry"],
        "irreversible_tools": {"create_return", "create_calendar_entry"},
    },
    "task_10": {
        "prompt": "Schedule pending bills on or before due dates while avoiding overdraft if possible.",
        "hard_constraints": ["Schedule all observed bills on or before due dates"],
        "preferences": ["Keep projected balance above $200"],
        "output_structure": {"success": "bool", "payment_confirmations": "list[object]"},
        "resource_uris": ["pending-bills://list"],
        "tool_names": ["schedule_payment"],
        "irreversible_tools": {"schedule_payment"},
        "behavior_checklist": [
            "Given date is 2026-04-22T12:00:00; the due window is the 3 days before that timestamp.",
            "Schedule due-window bills in due-date order only while the projected balance remains at least USD 200.",
            "If a due-window bill cannot be scheduled without dropping below USD 200, omit that payment and provide a non-empty overdraft_alert.",
            "Do not schedule bills outside the due window.",
        ],
    },
}


class TaskInterpreter:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def load(self, task_id: str) -> TaskSpec:
        normalized = normalize_task_id(task_id)
        descriptions = self._load_task_descriptions()
        tool_schemas = self._load_tool_schemas()
        raw = deepcopy(descriptions.get(normalized, {}))
        runtime = TASK_RUNTIME.get(normalized)
        if runtime is None:
            raise KeyError(f"Unsupported task id: {task_id}")

        merged = {**runtime, **raw}
        merged["resource_uris"] = runtime.get("resource_uris", [])
        merged["tool_names"] = runtime.get("tool_names", [])
        merged["irreversible_tools"] = runtime.get("irreversible_tools", set())
        selected_tool_schemas = [
            schema for schema in tool_schemas
            if schema.get("name") in set(merged["tool_names"])
        ]

        return TaskSpec(
            task_id=normalized,
            prompt=merged.get("prompt", ""),
            hard_constraints=list(merged.get("hard_constraints", [])),
            preferences=list(merged.get("preferences", [])),
            output_structure=clean_output_structure(dict(merged.get("output_structure", {"success": "bool"}))),
            resource_uris=list(merged.get("resource_uris", [])),
            tool_names=list(merged.get("tool_names", [])),
            tool_schemas=selected_tool_schemas,
            irreversible_tools=set(merged.get("irreversible_tools", set())),
            behavior_checklist=list(merged.get("behavior_checklist", [])),
        )

    def available_task_ids(self) -> list[str]:
        return sorted(TASK_RUNTIME)

    def _load_task_descriptions(self) -> dict[str, dict[str, Any]]:
        path = self.repo_root / "tasks_description.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {normalize_task_id(key): value for key, value in data.items()}

    def _load_tool_schemas(self) -> list[dict[str, Any]]:
        path = self.repo_root / "tool_schema.json"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("name")]


def normalize_task_id(task_id: str) -> str:
    lowered = task_id.strip().lower()
    if lowered.startswith("task_"):
        suffix = lowered.split("_", 1)[1]
        if suffix.isdigit():
            return f"task_{int(suffix):02d}"
    if lowered.startswith("t") and lowered[1:].isdigit():
        return f"task_{int(lowered[1:]):02d}"
    return lowered


def clean_output_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: clean_output_structure(child)
            for key, child in value.items()
            if key
        }
    if isinstance(value, list):
        return [clean_output_structure(item) for item in value]
    return value
