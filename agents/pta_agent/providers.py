from __future__ import annotations

import json
import os
import re
import asyncio
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import TaskSpec
from .state import StateManager


class ModelProvider(ABC):
    name = "base"
    model_id = "n/a"

    @abstractmethod
    async def propose(self, task: TaskSpec, state: StateManager, repair_context: str | None = None) -> dict[str, Any]:
        raise NotImplementedError


class ProviderRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


ANTHROPIC_SYSTEM_PROMPT = (
    "You propose exactly one JSON action for a policy-gated personal task agent. "
    "Return only JSON."
)


def anthropic_text_block(text: str, *, cache: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "text", "text": text}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def anthropic_user_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": "user", "content": content}


class MockProvider(ModelProvider):
    name = "mock"
    model_id = "deterministic-mock"

    async def propose(self, task: TaskSpec, state: StateManager, repair_context: str | None = None) -> dict[str, Any]:
        method = getattr(self, f"_propose_{task.task_id}", None)
        if method is None:
            return self._stop("unsupported_task", f"No mock strategy for {task.task_id}.")
        return method(state)

    def _propose_task_01(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("transportation://list"):
            return {"action": "read_resource", "resource_uri": "transportation://list"}
        ride = _find_by_id(state.get_resource("transportation://list"), "LY-1004")
        if not state.get_tool_results("create_travel_arrangement"):
            return {"action": "call_tool", "tool_name": "create_travel_arrangement", "arguments": {"ride_id": ride["id"]}}
        if not state.get_tool_results("create_calendar_entry"):
            return {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": ride["arrival_time"], "category": "RIDE"},
            }
        travel = state.get_tool_results("create_travel_arrangement")[0]["result"]
        calendar = state.get_tool_results("create_calendar_entry")[0]["result"]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "travel_confirmation": {"confirmation_id": travel["confirmation_id"], **ride},
                "calendar": {"confirmation_id": calendar["confirmation_id"]},
            },
        }

    def _propose_task_02(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("repair://options"):
            return {"action": "read_resource", "resource_uri": "repair://options"}
        option = next(
            item for item in state.get_resource("repair://options")
            if "laptop" in item["type_of_repair"].lower() and "battery" in item["type_of_repair"].lower()
        )
        if not state.get_tool_results("set_up_repair_appointment"):
            return {
                "action": "call_tool",
                "tool_name": "set_up_repair_appointment",
                "arguments": {"type_of_repair": option["type_of_repair"], "day_of_week": option["weekday"]},
            }
        confirmation = state.get_tool_results("set_up_repair_appointment")[0]["result"]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "repair_confirmation": {"confirmation_id": confirmation["confirmation_id"], **option},
            },
        }

    def _propose_task_03(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("catering://options"):
            return {"action": "read_resource", "resource_uri": "catering://options"}
        option = _find_by_id(state.get_resource("catering://options"), "cat_veg_safe")
        if not state.get_tool_results("set_catering_appointment"):
            return {
                "action": "call_tool",
                "tool_name": "set_catering_appointment",
                "arguments": {"menu_option": option["name"], "number_of_people": 3},
            }
        if not state.get_tool_results("send_invitations"):
            guests = [
                {"name": "One", "email": "one@example.com"},
                {"name": "Two", "email": "two@example.com"},
                {"name": "Three", "email": "three@example.com"},
            ]
            return {"action": "call_tool", "tool_name": "send_invitations", "arguments": {"guests": guests}}
        catering = state.get_tool_results("set_catering_appointment")[0]["result"]
        invitations = state.get_tool_results("send_invitations")[0]["result"]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "catering_confirmation": {"confirmation_id": catering["confirmation_id"], **{k: option[k] for k in ("name", "total", "vegetarian", "contains_nuts")}},
                "invite_log": invitations["msg"],
            },
        }

    def _propose_task_04(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("doctor://list"):
            return {"action": "read_resource", "resource_uri": "doctor://list"}
        doctor = next(
            item for item in state.get_resource("doctor://list")
            if item["specialty"] == "Dermatologist"
            and "Eczema" in item.get("supports", [])
            and item["copay"] <= 50
            and "Friday,16" in item.get("availability", [])
        )
        if not state.get_tool_results("set_up_doctor_appointment"):
            return {
                "action": "call_tool",
                "tool_name": "set_up_doctor_appointment",
                "arguments": {"doctor_name": doctor["name"], "appointment_time": "Friday,16"},
            }
        if not state.get_tool_results("create_calendar_entry"):
            return {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": "2026-05-08T16:00:00", "category": "MEDICAL"},
            }
        appointment = state.get_tool_results("set_up_doctor_appointment")[0]["result"]
        calendar = state.get_tool_results("create_calendar_entry")[0]["result"]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "appointment_confirmation": {
                    "confirmation_id": appointment["confirmation_id"],
                    "name": doctor["name"],
                    "specialty": doctor["specialty"],
                    "supports": doctor["supports"],
                    "copay": doctor["copay"],
                    "weekday": "Friday",
                    "time": "16:00",
                },
                "calendar": {"confirmation_id": calendar["confirmation_id"]},
            },
        }

    def _propose_task_05(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("troubleshoot://guide"):
            return {"action": "read_resource", "resource_uri": "troubleshoot://guide"}
        if not state.has_resource("troubleshoot://repair"):
            return {"action": "read_resource", "resource_uri": "troubleshoot://repair"}
        guide = next(item for item in state.get_resource("troubleshoot://guide") if "Washer not draining" in item["symptoms"])
        repair = next(item for item in state.get_resource("troubleshoot://repair") if item["appliance_type"] == "Washer")
        steps = [
            "Turn off and unplug the washer.",
            "Check the drain pump area for blockage.",
            "Clear debris from the drain pump filter.",
            "Run a short drain cycle to verify the washer drains properly.",
            "Use a washer repair service if the issue continues.",
        ]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "diagnosis": "Washer not draining",
                "likely_cause": guide["likely_cause"],
                "recommended_steps": steps,
                "repair_recommendation": {
                    "service_name": repair["name"],
                    "distance_miles": float(repair["distance_to"]),
                    "estimated_cost": repair["estimate"],
                },
            },
        }

    def _propose_task_06(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("household-bills://list"):
            return {"action": "read_resource", "resource_uri": "household-bills://list"}
        pending = [bill for bill in state.get_resource("household-bills://list") if not bill.get("settled")]
        done = {(item["arguments"]["bill_id"], item["arguments"]["amount"]) for item in state.get_tool_results("schedule_payment")}
        for bill in pending:
            if (bill["id"], bill["amount"]) not in done:
                return {
                    "action": "call_tool",
                    "tool_name": "schedule_payment",
                    "arguments": {"bill_id": bill["id"], "payment_date": bill["due"][:10], "amount": bill["amount"]},
                }
        total = sum(int(bill["amount"]) for bill in pending)
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "plan_summary": (
                    f"Scheduled {len(pending)} pending bills by their due dates. "
                    f"Total scheduled amount is {total}."
                ),
                "pending_bills": [
                    {
                        "bill_id": bill["id"],
                        "name": bill["name"],
                        "amount": bill["amount"],
                        "due_date": bill["due"][:10],
                        "settled": bill["settled"],
                    }
                    for bill in pending
                ],
                "scheduled_payments": [
                    {
                        "payment_confirmation_id": item["result"]["payment_confirmation_id"],
                        "bill_id": item["result"]["bill_id"],
                        "payment_date": item["result"]["payment_date"],
                        "amount": item["result"]["amount"],
                    }
                    for item in state.get_tool_results("schedule_payment")
                ],
                "alert": "" if total <= 120 else f"Pending bill total {total} exceeds budget 120.",
            },
        }

    def _propose_task_07(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("workout-sessions://list"):
            return {"action": "read_resource", "resource_uri": "workout-sessions://list"}
        sessions = state.get_resource("workout-sessions://list")
        selected_ids = [
            "strength_lower_01",
            "cardio_bike_01",
            "strength_push_01",
            "cardio_walk_01",
            "strength_upper_01",
            "cardio_swim_01",
        ]
        activities = [_find_by_key(sessions, "activity_id", activity_id) for activity_id in selected_ids]
        completed = len(state.get_tool_results("create_calendar_entry"))
        if completed < len(activities):
            activity = activities[completed]
            return {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": activity["start_time"], "category": "EXERCISE"},
            }
        confirmations = [
            item["result"]["confirmation_id"]
            for item in state.get_tool_results("create_calendar_entry")
        ]
        scheduled = [_activity_output(activity) for activity in activities]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "scheduled_cardio": [item for item in scheduled if item["activity_type"] == "cardio"],
                "scheduled_strength": [item for item in scheduled if item["activity_type"] == "strength"],
                "workout_calendar_confirmation": confirmations,
            },
        }

    def _propose_task_08(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("expenses://list"):
            return {"action": "read_resource", "resource_uri": "expenses://list"}
        expenses = [item for item in state.get_resource("expenses://list") if not item.get("priority")]
        if not state.get_tool_results("generate_report"):
            return {
                "action": "call_tool",
                "tool_name": "generate_report",
                "arguments": {
                    "expenses": expenses,
                    "reduction_goal": "Reduce non-priority spending by at least $100",
                    "suggestions": "Pause one streaming service, cap coffee spending, and batch rideshare trips.",
                },
            }
        suggestions = [
            {
                "category": "restaurants",
                "cut_amount": 80,
                "priority_category": False,
                "category_type": "discretionary",
                "reason": "Reduce restaurant spending by cooking more meals at home.",
            },
            {
                "category": "entertainment",
                "cut_amount": 45,
                "priority_category": False,
                "category_type": "discretionary",
                "reason": "Limit paid entertainment purchases for the month.",
            },
            {
                "category": "streaming",
                "cut_amount": 30,
                "priority_category": False,
                "category_type": "subscription",
                "reason": "Pause or downgrade one streaming subscription temporarily.",
            },
        ]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "generated_report": {
                    "savings_target": 150,
                    "total_reduction": sum(item["cut_amount"] for item in suggestions),
                    "report_summary": state.get_tool_results("generate_report")[0]["result"]["report"],
                    "suggestions": suggestions,
                },
            },
        }

    def _propose_task_09(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("online-purchase://return_options"):
            return {"action": "read_resource", "resource_uri": "online-purchase://return_options"}
        option = _find_by_id(state.get_resource("online-purchase://return_options"), "ret_drop_free")
        if not state.get_tool_results("create_return"):
            return {"action": "call_tool", "tool_name": "create_return", "arguments": {"id": option["id"]}}
        if not state.get_tool_results("create_calendar_entry"):
            return {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": f"{option['deadline']}T09:00:00", "category": "PRODUCT_RETURN"},
            }
        confirmation = state.get_tool_results("create_return")[0]["result"]
        calendar = state.get_tool_results("create_calendar_entry")[0]["result"]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "return": {
                    "return_id": confirmation["return_id"],
                    "label_id": confirmation["label_id"],
                    "free_return": option["cost"] == 0,
                    "delivery_method": option["delivery"],
                    "refund_method": option["refund_to"],
                },
                "calendar_entry": {
                    "confirmation_id": calendar["confirmation_id"],
                    "title": f"Return deadline for {option['id']}",
                    "deadline": option["deadline"],
                },
                "summary": "Scheduled a free drop-off return with refund to the original payment method.",
            },
        }

    def _propose_task_10(self, state: StateManager) -> dict[str, Any]:
        if not state.has_resource("pending-bills://list"):
            return {"action": "read_resource", "resource_uri": "pending-bills://list"}
        bills = state.get_resource("pending-bills://list")
        given_date = datetime.fromisoformat("2026-04-22T12:00:00")
        start_date = given_date - timedelta(days=3)
        due_bills = [
            bill for bill in bills
            if start_date <= datetime.fromisoformat(bill["due"]) <= given_date
        ]
        scheduled_amount = sum(
            float(item["arguments"].get("amount", 0))
            for item in state.get_tool_results("schedule_payment")
        )
        done = {(item["arguments"]["bill_id"], item["arguments"]["amount"]) for item in state.get_tool_results("schedule_payment")}
        for bill in due_bills:
            if (bill["id"], bill["amount"]) not in done:
                if 300 - scheduled_amount - float(bill["amount"]) < 200:
                    continue
                return {
                    "action": "call_tool",
                    "tool_name": "schedule_payment",
                    "arguments": {"bill_id": bill["id"], "payment_date": bill["due"][:10], "amount": bill["amount"]},
                }
        scheduled_ids = {item["arguments"]["bill_id"] for item in state.get_tool_results("schedule_payment")}
        omitted = [bill for bill in due_bills if bill["id"] not in scheduled_ids]
        return {
            "action": "finalize",
            "final_output": {
                "success": True,
                "payments": [
                    {"id": bill["id"], "due_date": bill["due"], "amount": bill["amount"]}
                    for bill in bills
                ],
                "scheduled_payments": [
                    {
                        "confirmation_id": item["result"]["confirmation_id"],
                        "bill_id": item["result"]["bill_id"],
                        "scheduled_date": item["result"]["scheduled_date"],
                    }
                    for item in state.get_tool_results("schedule_payment")
                ],
                "overdraft_alert": (
                    "Cannot schedule due bill(s) without dropping below the USD 200 minimum balance: "
                    + ", ".join(f"{bill['id']} (${bill['amount']})" for bill in omitted)
                    if omitted else ""
                ),
            },
        }

    def _stop(self, status: str, reason: str) -> dict[str, Any]:
        return {"action": "stop", "status": status, "reason": reason, "final_output": {"success": False, "reason": reason}}


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self.load_environment()
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model_id = self.model_id_from_env()
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the anthropic provider.")
        if not self.model_id:
            raise RuntimeError("ANTHROPIC_MODEL is required for the anthropic provider.")
        self.rate_limit_retries = int(os.environ.get("ANTHROPIC_RATE_LIMIT_RETRIES", "1"))
        self.rate_limit_backoff_seconds = float(os.environ.get("ANTHROPIC_RATE_LIMIT_BACKOFF_SECONDS", "65"))
        self.active_task_id: str | None = None
        self.last_usage: dict[str, Any] | None = None

    @staticmethod
    def load_environment() -> None:
        load_dotenv()

    @staticmethod
    def model_id_from_env() -> str:
        return os.environ.get("ANTHROPIC_MODEL", "")

    async def propose(self, task: TaskSpec, state: StateManager, repair_context: str | None = None) -> dict[str, Any]:
        if self.active_task_id != task.task_id:
            self._reset_conversation(task.task_id)

        user_message = self._build_user_message(task, state, repair_context)
        body = {
            "model": self.model_id,
            "max_tokens": 1200,
            "temperature": 0,
            "system": self._build_system(),
            "messages": [user_message],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        payload = await self._send_request(request)
        self.last_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        text = "\n".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
        return parse_model_json(text)

    async def _send_request(self, request: urllib.request.Request) -> dict[str, Any]:
        for attempt in range(self.rate_limit_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429:
                    retry_after = retry_after_seconds(exc, self.rate_limit_backoff_seconds)
                    if attempt < self.rate_limit_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    raise ProviderRateLimitError(
                        f"Anthropic API rate limit exceeded after {attempt + 1} attempt(s).",
                        retry_after_seconds=retry_after,
                    ) from exc
                raise RuntimeError(f"Anthropic API HTTP {exc.code}: {body[:500]}") from exc
        raise ProviderRateLimitError("Anthropic API rate limit exceeded.")

    def _build_system(self) -> list[dict[str, Any]]:
        return [anthropic_text_block(ANTHROPIC_SYSTEM_PROMPT, cache=True)]

    def _build_user_message(self, task: TaskSpec, state: StateManager, repair_context: str | None) -> dict[str, Any]:
        return anthropic_user_message(
            [
                anthropic_text_block(build_initial_anthropic_prompt(task), cache=True),
                anthropic_text_block(build_turn_full_state_prompt(task, state, repair_context)),
            ]
        )

    def _reset_conversation(self, task_id: str) -> None:
        self.active_task_id = task_id


def build_provider(name: str) -> ModelProvider:
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"Unknown provider: {name}")


def build_initial_anthropic_prompt(task: TaskSpec) -> str:
    return json.dumps(
        {
            "task": {
                "task_id": task.task_id,
                "prompt": task.prompt,
                "hard_constraints": task.hard_constraints,
                "preferences": task.preferences,
                "resource_uris": task.resource_uris,
                "tool_names": task.tool_names,
                "tool_schemas": task.tool_schemas,
                "output_structure": task.output_structure,
            },
            "supported_actions": ["read_resource", "call_tool", "finalize", "ask_clarification", "stop"],
            "action_shapes": {
                "read_resource": {"action": "read_resource", "resource_uri": "<one of task.resource_uris>"},
                "call_tool": {"action": "call_tool", "tool_name": "<one of task.tool_names>", "arguments": {"field": "value"}},
                "finalize": {"action": "finalize", "final_output": "<object matching task.output_structure>"},
                "ask_clarification": {"action": "ask_clarification", "message": "<question>"},
                "stop": {"action": "stop", "status": "<failure status>", "reason": "<reason>"},
            },
            "instructions": [
                "Return one JSON object only.",
                "For call_tool, put all tool inputs inside the arguments object.",
                "Use only argument names allowed by the selected tool's input_schema.",
                "Do not claim confirmation IDs unless they are already in state.tool_results.",
                "Prefer reading resources before tool calls.",
                "Hard constraints override preferences.",
                "This task context is stable and cacheable; each request also includes the current full StateManager snapshot.",
                "Use the StateManager snapshot before claiming resources or tool results.",
            ],
        },
        ensure_ascii=False,
        default=str,
    )


def build_turn_full_state_prompt(
    task: TaskSpec,
    state: StateManager,
    repair_context: str | None,
) -> str:
    return json.dumps(
        {
            "task_id": task.task_id,
            "state": {
                "resources_read": state.resources,
                "tool_results": state.tool_results,
                "policy_violations": state.policy_violations,
                "failed_attempts": state.failed_attempts[-3:],
                "summary": {
                    "resource_uris_read": sorted(state.resources),
                    "tools_called": [item["tool_name"] for item in state.tool_results],
                    "tool_count": len(state.tool_results),
                    "policy_violation_count": len(state.policy_violations),
                    "failed_attempt_count": len(state.failed_attempts),
                },
            },
            "repair_context": repair_context,
            "instructions": [
                "Return exactly one next action JSON object.",
                "Use the cached task context for allowed resources, tools, tool schemas, hard constraints, preferences, and output structure.",
                "If repair_context is present, fix the previous mistake.",
                "Do not repeat resource reads or irreversible tool calls already present in state.",
                "For call_tool, use arguments exactly matching the tool input_schema.",
                "Only finalize after all required tool-backed evidence exists.",
            ],
        },
        ensure_ascii=False,
        default=str,
    )


def parse_model_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Anthropic response did not contain text content.")
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Anthropic JSON response must be an object.")
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    candidate = extract_first_json_object(stripped)
    if candidate:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Anthropic response was not valid JSON action. Response starts: {stripped[:300]!r}")


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise LookupError(f"Could not find id {item_id}.")


def _find_by_key(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for item in items:
        if item.get(key) == value:
            return item
    raise LookupError(f"Could not find {key}={value}.")


def _activity_output(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_id": activity["activity_id"],
        "activity_type": activity["activity_type"],
        "muscle_group": activity["muscle_group"],
        "weekday": activity["day"],
        "start_time": activity["start_time"],
        "end_time": activity["end_time"],
    }


def load_dotenv() -> None:
    path = find_repo_root() / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def find_repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "tasks_description.json").exists():
            return parent
    return Path.cwd()


def retry_after_seconds(exc: urllib.error.HTTPError, default_seconds: float) -> float:
    header = exc.headers.get("retry-after") if exc.headers else None
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            return default_seconds
    return default_seconds
