from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .models import TaskSpec
from .policy import task_07_final_reasons
from .state import StateManager


CONFIRMATION_KEYS = {
    "confirmation_id",
    "payment_confirmation_id",
    "return_id",
    "label_id",
}


@dataclass
class VerificationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors}


class Verifier:
    def verify(self, task: TaskSpec, state: StateManager, output: dict[str, Any]) -> VerificationResult:
        errors: list[str] = []
        errors.extend(validate_schema(task.output_structure, output, path="$"))
        errors.extend(self._verify_evidence(task, state, output))
        return VerificationResult(ok=not errors, errors=errors)

    def _verify_evidence(self, task: TaskSpec, state: StateManager, output: dict[str, Any]) -> list[str]:
        if output.get("success") is False:
            return []
        method = getattr(self, f"_verify_{task.task_id}", None)
        if method is None:
            return verify_generic_confirmations(state, output)
        return method(state, output)

    def _verify_task_01(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        travel_results = state.get_tool_results("create_travel_arrangement")
        calendar_results = state.get_tool_results("create_calendar_entry")
        ride = output.get("travel_confirmation", {})
        if not travel_results:
            errors.append("Missing travel tool evidence.")
        elif ride.get("confirmation_id") != travel_results[0]["result"].get("confirmation_id"):
            errors.append("Travel confirmation_id is not tool-backed.")
        if not calendar_results:
            errors.append("Missing calendar evidence.")
        selected_ride_id = ride.get("id")
        if not selected_ride_id and travel_results:
            selected_ride_id = travel_results[0]["arguments"].get("ride_id") or travel_results[0]["result"].get("ride_id")
        observed = next((item for item in state.get_resource("transportation://list", []) if item.get("id") == selected_ride_id), None)
        if not observed:
            errors.append("Final ride is not grounded in resource data.")
        else:
            for key in ("arrival_time", "departure_time", "cost", "surge_pricing", "rideshare", "from", "to"):
                if ride.get(key) != observed.get(key):
                    errors.append(f"Ride field {key} does not match observed resource.")
            arrival = datetime.fromisoformat(ride["arrival_time"])
            if arrival > datetime.fromisoformat("2026-05-02T12:00:00") - timedelta(hours=2):
                errors.append("Ride violates 2-hour arrival constraint.")
            if ride.get("cost", 999999) > 45:
                errors.append("Ride violates budget.")
            if ride.get("surge_pricing"):
                errors.append("Ride violates no-surge constraint.")
            if ride.get("from", "").lower() != "chicago" or ride.get("to", "").lower() != "urbana":
                errors.append("Ride violates route constraint.")
        return errors

    def _verify_task_02(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        repair = output.get("repair_confirmation", {})
        observed = next((item for item in state.get_resource("repair://options", []) if item.get("type_of_repair") == repair.get("type_of_repair")), None)
        if not state.get_tool_results("set_up_repair_appointment"):
            errors.append("Missing repair appointment evidence.")
        if not observed:
            errors.append("Repair confirmation is not grounded in resource data.")
            return errors
        lowered = observed["type_of_repair"].lower()
        if "laptop" not in lowered or "battery" not in lowered:
            errors.append("Repair type is not laptop battery.")
        if not observed.get("in_network"):
            errors.append("Repair is out-of-network.")
        if observed.get("weekday", "").lower() == "thursday":
            errors.append("Repair appointment is on Thursday.")
        if observed.get("deductible", 999999) > 120:
            errors.append("Repair deductible exceeds 120.")
        for key in ("in_network", "deductible", "weekday", "current_week"):
            if repair.get(key) != observed.get(key):
                errors.append(f"Repair field {key} does not match observed resource.")
        return errors

    def _verify_task_03(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        catering = output.get("catering_confirmation", {})
        observed = next((item for item in state.get_resource("catering://options", []) if item.get("name") == catering.get("name")), None)
        if not state.get_tool_results("set_catering_appointment"):
            errors.append("Missing catering appointment evidence.")
        if not state.get_tool_results("send_invitations"):
            errors.append("Missing invitation evidence.")
        if not observed:
            errors.append("Catering confirmation is not grounded in resource data.")
            return errors
        if observed.get("total", 999999) > 150:
            errors.append("Catering violates budget.")
        if not observed.get("vegetarian"):
            errors.append("Catering lacks vegetarian option.")
        if observed.get("contains_nuts"):
            errors.append("Catering violates no-nuts preference.")
        for key in ("total", "vegetarian", "contains_nuts"):
            if catering.get(key) != observed.get(key):
                errors.append(f"Catering field {key} does not match observed resource.")
        invite_log = output.get("invite_log", [])
        for email in ("one@example.com", "two@example.com", "three@example.com"):
            if not any(email in entry for entry in invite_log):
                errors.append(f"Missing invitation log for {email}.")
        return errors

    def _verify_task_04(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        appointment = output.get("appointment_confirmation", {})
        doctor_results = state.get_tool_results("set_up_doctor_appointment")
        calendar_results = state.get_tool_results("create_calendar_entry")
        if not doctor_results:
            errors.append("Missing doctor appointment evidence.")
        elif appointment.get("confirmation_id") != doctor_results[0]["result"].get("confirmation_id"):
            errors.append("Doctor appointment confirmation_id is not tool-backed.")
        if not calendar_results:
            errors.append("Missing calendar evidence.")

        observed = next((item for item in state.get_resource("doctor://list", []) if item.get("name") == appointment.get("name")), None)
        if not observed:
            errors.append("Appointment provider is not grounded in doctor resource.")
            return errors
        if observed.get("specialty") != "Dermatologist":
            errors.append("Provider is not a dermatologist.")
        if "Eczema" not in observed.get("supports", []):
            errors.append("Provider does not support eczema.")
        if observed.get("copay", 999999) > 50:
            errors.append("Provider copay exceeds 50.")
        for key in ("specialty", "supports", "copay"):
            if appointment.get(key) != observed.get(key):
                errors.append(f"Appointment field {key} does not match observed resource.")
        return errors

    def _verify_task_05(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        steps = output.get("recommended_steps")
        if not isinstance(steps, list) or not all(isinstance(step, str) and step.strip() for step in steps):
            errors.append("Task_05 requires clear top-level recommended_steps.")
        repair = output.get("repair_recommendation", {})
        if isinstance(repair, dict) and "recommended_steps" in repair:
            errors.append("Task_05 should keep recommended_steps top-level, not nested under repair_recommendation.")
        return errors

    def _verify_task_06(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        observed = state.get_resource("household-bills://list", []) or []
        expected_ids = {bill.get("id") for bill in observed if not bill.get("settled")}
        pending_bills = output.get("pending_bills", [])
        final_ids = {bill.get("bill_id") for bill in pending_bills if isinstance(bill, dict)}
        if final_ids != expected_ids:
            errors.append("Task_06 pending_bills do not match observed unsettled bills.")
        if any(isinstance(bill, dict) and bill.get("settled") is not False for bill in pending_bills):
            errors.append("Task_06 pending_bills contains a settled bill.")
        scheduled_ids = {item["arguments"].get("bill_id") for item in state.get_tool_results("schedule_payment")}
        if scheduled_ids != expected_ids:
            errors.append("Task_06 scheduled payments do not match unsettled bills.")
        return errors

    def _verify_task_07(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        errors.extend(task_07_final_reasons(output, state))
        return errors

    def _verify_task_10(self, state: StateManager, output: dict[str, Any]) -> list[str]:
        errors = verify_generic_confirmations(state, output)
        scheduled_ids = {item["arguments"].get("bill_id") for item in state.get_tool_results("schedule_payment")}
        output_scheduled_ids = {
            payment.get("bill_id")
            for payment in output.get("scheduled_payments", [])
            if isinstance(payment, dict)
        }
        if output_scheduled_ids != scheduled_ids:
            errors.append("Task_10 scheduled_payments do not match successful tool calls.")
        if task_10_projected_balance(output, scheduled_ids) < 200:
            errors.append("Task_10 projected balance falls below 200.")
        omitted_due_ids = task_10_omitted_due_ids(output, scheduled_ids)
        if omitted_due_ids:
            alert = output.get("overdraft_alert")
            if not isinstance(alert, str) or not alert.strip():
                errors.append("Task_10 omitted due bills require a non-empty overdraft_alert.")
        return errors


def verify_generic_confirmations(state: StateManager, output: dict[str, Any]) -> list[str]:
    observed = state.confirmation_values()
    claimed: set[str] = set()
    collect_claimed_ids(output, claimed)
    return [f"Claimed confirmation/id value is not tool-backed: {value}" for value in sorted(claimed - observed)]


def collect_claimed_ids(value: Any, claimed: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in CONFIRMATION_KEYS or "confirmation" in key:
                if isinstance(child, str):
                    claimed.add(child)
                elif isinstance(child, list):
                    claimed.update(item for item in child if isinstance(item, str))
            collect_claimed_ids(child, claimed)
    elif isinstance(value, list):
        for item in value:
            collect_claimed_ids(item, claimed)


def validate_schema(schema: Any, value: Any, path: str) -> list[str]:
    errors: list[str] = []
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            return [f"{path} must be an object."]
        for key, child_schema in schema.items():
            if key not in value:
                errors.append(f"{path}.{key} is missing.")
            else:
                errors.extend(validate_schema(child_schema, value[key], f"{path}.{key}"))
        return errors
    if schema == "bool" and not isinstance(value, bool):
        errors.append(f"{path} must be bool.")
    elif schema == "string" and not isinstance(value, str):
        errors.append(f"{path} must be string.")
    elif schema == "int" and not isinstance(value, int):
        errors.append(f"{path} must be int.")
    elif schema == "object" and not isinstance(value, dict):
        errors.append(f"{path} must be object.")
    elif schema == "list[string]":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{path} must be list[string].")
    elif schema == "list[object]":
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            errors.append(f"{path} must be list[object].")
    return errors


def task_10_projected_balance(output: dict[str, Any], scheduled_ids: set[str]) -> float:
    amounts = {
        payment.get("id"): float(payment.get("amount", 0))
        for payment in output.get("payments", [])
        if isinstance(payment, dict)
    }
    return 300.0 - sum(amounts.get(bill_id, 0.0) for bill_id in scheduled_ids)


def task_10_omitted_due_ids(output: dict[str, Any], scheduled_ids: set[str]) -> set[str]:
    given_date = datetime.fromisoformat("2026-04-22T12:00:00")
    start_date = given_date - timedelta(days=3)
    omitted = set()
    for payment in output.get("payments", []):
        if not isinstance(payment, dict):
            continue
        try:
            due_date = datetime.fromisoformat(str(payment.get("due_date") or payment.get("due")))
        except (TypeError, ValueError):
            continue
        bill_id = payment.get("id")
        if start_date <= due_date <= given_date and bill_id not in scheduled_ids:
            omitted.add(bill_id)
    return omitted
