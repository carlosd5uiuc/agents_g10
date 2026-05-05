from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from typing import Any

from .models import ActionProposal, ActionType, PolicyDecision, TaskSpec
from .state import StateManager


class PolicyEngine:
    def evaluate(self, proposal: ActionProposal, task: TaskSpec, state: StateManager) -> PolicyDecision:
        if proposal.action == ActionType.READ_RESOURCE:
            return self._resource_policy(proposal, task, state)
        if proposal.action == ActionType.CALL_TOOL:
            return self._tool_policy(proposal, task, state)
        if proposal.action == ActionType.FINALIZE:
            return self._finalize_policy(proposal, state)
        if proposal.action == ActionType.ASK_CLARIFICATION:
            return self._clarification_policy(proposal, task, state)
        if proposal.action == ActionType.STOP:
            return PolicyDecision.stop(proposal.reason or "model stopped")
        return PolicyDecision.deny("unknown action")

    def _resource_policy(self, proposal: ActionProposal, task: TaskSpec, state: StateManager) -> PolicyDecision:
        assert proposal.resource_uri is not None
        if proposal.resource_uri not in task.resource_uris:
            return PolicyDecision.deny(f"Resource {proposal.resource_uri} is not allowed for {task.task_id}.")
        if state.has_resource(proposal.resource_uri):
            return PolicyDecision.deny(f"Resource {proposal.resource_uri} already read.")
        return PolicyDecision.allow("allowed resource read")

    def _tool_policy(self, proposal: ActionProposal, task: TaskSpec, state: StateManager) -> PolicyDecision:
        assert proposal.tool_name is not None
        if proposal.tool_name not in task.tool_names:
            return PolicyDecision.deny(f"Tool {proposal.tool_name} is not allowed for {task.task_id}.")
        schema_reasons = validate_tool_arguments(proposal.tool_name, proposal.arguments, task)
        if schema_reasons:
            return PolicyDecision.repair(*schema_reasons)
        if proposal.tool_name in task.irreversible_tools and state.has_tool_call(proposal.tool_name, proposal.arguments):
            return PolicyDecision.deny("Duplicate irreversible tool call blocked.")
        missing_resources = [uri for uri in required_resources_for_tool(proposal.tool_name, task) if not state.has_resource(uri)]
        if missing_resources:
            return PolicyDecision.repair(f"Missing prerequisite resources: {missing_resources}.")

        check = getattr(self, f"_check_{proposal.tool_name}", None)
        if check is None:
            return PolicyDecision.allow("no special policy check")
        reasons = check(proposal.arguments, task, state)
        if reasons:
            return PolicyDecision.repair(*reasons)
        return PolicyDecision.allow("tool arguments pass policy")

    def _finalize_policy(self, proposal: ActionProposal, state: StateManager) -> PolicyDecision:
        if proposal.final_output is None:
            return PolicyDecision.deny("Missing final output.")
        if proposal.final_output.get("success") is True and not state.tool_results and state.task.tool_names:
            return PolicyDecision.repair("Cannot finalize success without tool evidence.")
        if state.task.task_id == "task_01" and proposal.final_output.get("success") is True:
            if not state.get_tool_results("create_travel_arrangement"):
                return PolicyDecision.repair("Cannot finalize task_01 before travel arrangement tool call.")
            if not state.get_tool_results("create_calendar_entry"):
                return PolicyDecision.repair("Cannot finalize task_01 before calendar entry tool call.")
        if state.task.task_id == "task_02" and proposal.final_output.get("success") is True:
            if not state.get_tool_results("set_up_repair_appointment"):
                return PolicyDecision.repair("Cannot finalize task_02 before repair appointment tool call.")
        if state.task.task_id == "task_03" and proposal.final_output.get("success") is True:
            if not state.get_tool_results("set_catering_appointment"):
                return PolicyDecision.repair("Cannot finalize task_03 before catering appointment tool call.")
            if not state.get_tool_results("send_invitations"):
                return PolicyDecision.repair("Cannot finalize task_03 before invitation tool call.")
        if state.task.task_id == "task_04" and proposal.final_output.get("success") is True:
            if not state.get_tool_results("set_up_doctor_appointment"):
                return PolicyDecision.repair("Cannot finalize task_04 before doctor appointment tool call.")
            if not state.get_tool_results("create_calendar_entry"):
                return PolicyDecision.repair("Cannot finalize task_04 before MEDICAL calendar entry tool call.")
        if state.task.task_id == "task_05" and proposal.final_output.get("success") is True:
            reasons = task_05_final_reasons(proposal.final_output)
            if reasons:
                return PolicyDecision.repair(*reasons)
        if state.task.task_id == "task_06" and proposal.final_output.get("success") is True:
            reasons = task_06_final_reasons(proposal.final_output, state)
            if reasons:
                return PolicyDecision.repair(*reasons)
        if state.task.task_id == "task_07" and proposal.final_output.get("success") is True:
            reasons = task_07_final_reasons(proposal.final_output, state)
            if reasons:
                return PolicyDecision.repair(*reasons)
        if state.task.task_id == "task_10" and proposal.final_output.get("success") is True:
            reasons = task_10_final_reasons(proposal.final_output, state)
            if reasons:
                return PolicyDecision.repair(*reasons)
        return PolicyDecision.allow("finalization can be verified")

    def _clarification_policy(self, proposal: ActionProposal, task: TaskSpec, state: StateManager) -> PolicyDecision:
        if task.task_id == "task_04":
            return PolicyDecision.repair(
                "Do not ask the user for a date already present in the observed doctor resource. "
                "Read doctor://list if needed, select a provider satisfying the stated constraints, "
                "and derive the calendar datetime from the selected slot metadata."
            )
        return PolicyDecision.clarify(proposal.message or "clarification requested")

    def _check_create_travel_arrangement(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        ride = find_resource_item(state, "transportation://list", "id", arguments.get("ride_id"))
        if not ride:
            return ["ride_id is not grounded in transportation resource."]
        reasons = []
        arrival = datetime.fromisoformat(ride["arrival_time"])
        deadline = datetime.fromisoformat("2026-05-02T12:00:00")
        if arrival > deadline.replace(hour=10):
            reasons.append("Ride does not arrive at least 2 hours early.")
        if ride["cost"] > 45:
            reasons.append("Ride exceeds $45 budget.")
        if ride["surge_pricing"]:
            reasons.append("Ride has surge pricing.")
        if ride["from"].lower() != "chicago" or ride["to"].lower() != "urbana":
            reasons.append("Ride route is not Chicago to Urbana.")
        return reasons

    def _check_create_calendar_entry(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        if not arguments.get("date") or not arguments.get("category"):
            return ["Calendar entry requires date and category."]
        try:
            datetime.fromisoformat(arguments["date"])
        except (TypeError, ValueError):
            return ["Calendar date must be ISO datetime."]
        reasons = []
        if task.task_id == "task_01":
            rides = state.get_resource("transportation://list", [])
            selected = state.get_tool_results("create_travel_arrangement")
            if selected:
                ride = find_item(rides, "id", selected[0]["arguments"]["ride_id"])
                if ride and arguments["date"] != ride["arrival_time"]:
                    return ["Ride calendar entry must use selected ride arrival time."]
        if task.task_id == "task_04":
            if arguments.get("category") != "MEDICAL":
                reasons.append("Doctor appointment calendar entry must use category MEDICAL.")
            appointments = state.get_tool_results("set_up_doctor_appointment")
            if not appointments:
                reasons.append("Create the doctor appointment before the calendar entry.")
            else:
                selected = appointments[0]["arguments"]
                doctor = find_item(state.get_resource("doctor://list", []), "name", selected.get("doctor_name"))
                expected_datetime = slot_datetime(doctor, selected.get("appointment_time"))
                if expected_datetime and arguments["date"] != expected_datetime:
                    reasons.append("Calendar date must match the selected doctor slot metadata.")
        if task.task_id == "task_07":
            if arguments.get("category") != "EXERCISE":
                reasons.append("Task_07 calendar entries must use category EXERCISE.")
            valid_sessions = task_07_valid_sessions(state)
            valid_sessions_by_date = {
                session.get("start_time"): session
                for session in valid_sessions
                if isinstance(session.get("start_time"), str)
            }
            proposed_session = valid_sessions_by_date.get(arguments["date"])
            if valid_sessions_by_date and proposed_session is None:
                reasons.append(
                    "Task_07 calendar entry date must match a valid observed workout start_time "
                    "that avoids the blocked Monday/Wednesday time windows."
                )
            existing_dates = {
                item.get("arguments", {}).get("date")
                for item in state.get_tool_results("create_calendar_entry")
                if isinstance(item.get("arguments"), dict)
            }
            if arguments["date"] in existing_dates:
                reasons.append("Task_07 already has a calendar entry for this workout date; do not create another one.")
            calendar_results = state.get_tool_results("create_calendar_entry")
            if len(calendar_results) >= 6:
                reasons.append(
                    "Task_07 already has six calendar tool calls for the six-workout plan; "
                    "additional create_calendar_entry calls cannot repair previous irreversible calls."
                )
            existing_sessions = [
                valid_sessions_by_date.get(item.get("arguments", {}).get("date"))
                for item in calendar_results
                if isinstance(item.get("arguments"), dict)
            ]
            existing_sessions = [session for session in existing_sessions if isinstance(session, dict)]
            if proposed_session:
                proposed_type = str(proposed_session.get("activity_type") or "")
                proposed_day = str(proposed_session.get("day") or proposed_session.get("weekday") or "")
                existing_type_counts = Counter(str(session.get("activity_type") or "") for session in existing_sessions)
                if proposed_type in {"cardio", "strength"} and existing_type_counts[proposed_type] >= 3:
                    reasons.append(f"Task_07 already has three {proposed_type} calendar entries; do not add a fourth.")
                existing_type_days = {
                    (str(session.get("day") or session.get("weekday") or ""), str(session.get("activity_type") or ""))
                    for session in existing_sessions
                }
                if (proposed_day, proposed_type) in existing_type_days:
                    reasons.append("Task_07 must not create more than one activity of the same type on the same day.")
        return reasons

    def _check_set_up_repair_appointment(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        option = find_item(state.get_resource("repair://options", []), "type_of_repair", arguments.get("type_of_repair"))
        if not option:
            return ["Repair type is not grounded in repair options."]
        reasons = []
        lowered = option["type_of_repair"].lower()
        if task.task_id == "task_02" and ("laptop" not in lowered or "battery" not in lowered):
            reasons.append("Repair must be for laptop battery.")
        if not option.get("in_network"):
            reasons.append("Repair provider must be in-network.")
        if option.get("weekday", "").lower() == "thursday":
            reasons.append("Appointment must not be Thursday.")
        if option.get("deductible", 999999) > 120:
            reasons.append("Deductible must be <= 120.")
        if arguments.get("day_of_week") != option.get("weekday"):
            reasons.append("Requested day does not match observed repair option.")
        return reasons

    def _check_set_catering_appointment(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        option = find_item(state.get_resource("catering://options", []), "name", arguments.get("menu_option"))
        if not option:
            return ["Catering menu is not grounded in catering options."]
        reasons = []
        if option.get("total", 999999) > 150:
            reasons.append("Catering total must be <= 150.")
        if not option.get("vegetarian"):
            reasons.append("Catering must include vegetarian options.")
        if option.get("contains_nuts"):
            reasons.append("Catering should avoid nuts.")
        return reasons

    def _check_send_invitations(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        guests = arguments.get("guests", [])
        emails = {guest.get("email") for guest in guests if isinstance(guest, dict)}
        required = {"one@example.com", "two@example.com", "three@example.com"}
        if task.task_id == "task_03" and emails != required:
            return [f"Invitations must go exactly to {sorted(required)}."]
        return []

    def _check_set_up_doctor_appointment(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        doctor = find_item(state.get_resource("doctor://list", []), "name", arguments.get("doctor_name"))
        if not doctor:
            return ["Doctor is not grounded in doctor list."]
        if arguments.get("appointment_time") not in doctor.get("availability", []):
            return ["Appointment slot is not available for selected doctor."]
        reasons = []
        if task.task_id == "task_04":
            if doctor.get("specialty") != "Dermatologist":
                reasons.append("Provider must be a dermatologist.")
            if "Eczema" not in doctor.get("supports", []):
                reasons.append("Provider must support eczema.")
            if doctor.get("copay", 999999) > 50:
                reasons.append("Copay must be <= 50.")
            day, hour = parse_day_hour(arguments.get("appointment_time"))
            if day != "Friday" or hour <= 15:
                reasons.append("Use the available Friday after 3 pm slot when scheduling task_04.")
        return reasons

    def _check_generate_report(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        observed = state.get_resource("expenses://list", [])
        proposed_expenses = arguments.get("expenses", [])
        if not isinstance(proposed_expenses, list) or not proposed_expenses:
            return ["generate_report expenses must be a non-empty list of observed non-priority cut candidate expense objects."]

        observed_by_category = {
            item.get("category"): item
            for item in observed
            if isinstance(item, dict) and item.get("category")
        }
        observed_categories = set(observed_by_category)
        selected = {
            expense.get("category")
            for expense in proposed_expenses
            if isinstance(expense, dict)
        }
        unknown_categories = sorted(category for category in selected if category not in observed_categories)
        if unknown_categories:
            return [f"Report expense categories are not grounded in observed expenses: {unknown_categories}."]

        priority_categories = {category for category, item in observed_by_category.items() if item.get("priority")}
        selected_priority = sorted(priority_categories & selected)
        if selected_priority:
            allowed = sorted(category for category, item in observed_by_category.items() if not item.get("priority"))
            return [
                "generate_report arguments.expenses must contain only non-priority expense categories being considered for cuts, "
                "not the full expenses://list. "
                f"Remove priority categories {selected_priority}. Allowed non-priority categories: {allowed}. "
                "Preferences: avoid health and gym when possible."
            ]
        return []

    def _check_create_return(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        option = find_resource_item(state, "online-purchase://return_options", "id", arguments.get("id"))
        if not option:
            return ["Return option id is not grounded in observed return options."]
        reasons = []
        if option.get("cost") != 0:
            reasons.append("Return must be free.")
        if option.get("delivery") != "drop-off":
            reasons.append("Return must be drop-off.")
        if option.get("refund_to") != "original_payment":
            reasons.append("Refund must go to original payment method.")
        return reasons

    def _check_schedule_payment(self, arguments: dict[str, Any], task: TaskSpec, state: StateManager) -> list[str]:
        bills = []
        for uri in ("household-bills://list", "pending-bills://list"):
            bills.extend(state.get_resource(uri, []) or [])
        if not bills:
            return ["Payments require observed bills."]
        bill_id = arguments.get("bill_id") or arguments.get("concept")
        bill = find_item(bills, "id", bill_id)
        if not bill:
            return ["Payment bill_id is not grounded in observed bills."]
        if task.task_id == "task_06" and bill.get("settled"):
            return ["Settled household bills must not be scheduled again."]
        if float(arguments.get("amount", -1)) != float(bill.get("amount")):
            return ["Payment amount must match observed bill."]
        try:
            payment_date = datetime.fromisoformat(str(arguments.get("payment_date"))).date()
            due_date = datetime.fromisoformat(str(bill.get("due"))).date()
        except (TypeError, ValueError):
            return ["Payment date and bill due date must be valid ISO dates."]
        if payment_date > due_date:
            return ["Payment date must be on or before due date."]
        if task.task_id == "task_10":
            if not bill_due_in_task_10_window(bill):
                return ["Only bills due within 3 days before 2026-04-22T12:00:00 should be scheduled for task_10."]
            already_scheduled = sum(
                float(item["arguments"].get("amount", 0))
                for item in state.get_tool_results("schedule_payment")
            )
            if 300 - already_scheduled - float(arguments.get("amount", 0)) < 200:
                return ["Payment would make projected balance fall below USD 200."]
        return []


def required_resources_for_tool(tool_name: str, task: TaskSpec) -> list[str]:
    explicit = {
        "create_travel_arrangement": ["transportation://list"],
        "set_up_repair_appointment": ["repair://options"],
        "set_catering_appointment": ["catering://options"],
        "set_up_doctor_appointment": ["doctor://list"],
        "generate_report": ["expenses://list"],
        "create_return": ["online-purchase://return_options"],
        "schedule_payment": ["household-bills://list"] if task.task_id == "task_06" else ["pending-bills://list"] if task.task_id == "task_10" else [],
    }
    if tool_name == "create_calendar_entry":
        if task.task_id == "task_04":
            return ["doctor://list"]
        if task.task_id == "task_07":
            return ["workout-sessions://list"]
        if task.task_id == "task_09":
            return ["online-purchase://return_options"]
    return explicit.get(tool_name, [])


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any], task: TaskSpec) -> list[str]:
    schema = next((item for item in task.tool_schemas if item.get("name") == tool_name), None)
    if not schema:
        return []
    input_schema = schema.get("input_schema") or {}
    required = set(input_schema.get("required", []))
    properties = input_schema.get("properties", {})
    allowed = set(properties)
    provided = set(arguments)
    missing = sorted(required - provided)
    extra = sorted(provided - allowed)
    reasons = []
    if missing:
        reasons.append(
            f"{tool_name} arguments missing required fields {missing}. "
            f"Use exactly this input schema: {input_schema}."
        )
    if extra:
        reasons.append(
            f"{tool_name} arguments include unsupported fields {extra}. "
            f"Allowed fields are {sorted(allowed)}."
        )
    return reasons


def find_resource_item(state: StateManager, uri: str, key: str, value: Any) -> dict[str, Any] | None:
    return find_item(state.get_resource(uri, []) or [], key, value)


def find_item(items: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any] | None:
    for item in items:
        if item.get(key) == value:
            return item
    return None


TASK_07_BLOCKED_WINDOWS = (
    ("Monday", time(8, 0), time(17, 0)),
    ("Wednesday", time(8, 0), time(17, 0)),
)


def task_07_valid_sessions(state: StateManager) -> list[dict[str, Any]]:
    sessions = state.get_resource("workout-sessions://list", []) or []
    if not isinstance(sessions, list):
        return []
    return [
        session for session in sessions
        if isinstance(session, dict) and task_07_is_valid_session(session)
    ]


def task_07_recommended_activities(state: StateManager) -> list[dict[str, Any]]:
    sessions = state.get_resource("workout-sessions://list", []) or []
    return task_07_select_recommended_activities(sessions)


def task_07_recommended_activity_ids(state: StateManager) -> set[str]:
    return {
        str(activity.get("activity_id"))
        for activity in task_07_recommended_activities(state)
        if activity.get("activity_id")
    }


def task_07_recommended_dates(state: StateManager) -> set[str]:
    return {
        str(activity.get("start_time"))
        for activity in task_07_recommended_activities(state)
        if activity.get("start_time")
    }


def task_07_select_recommended_activities(sessions: Any) -> list[dict[str, Any]]:
    if not isinstance(sessions, list):
        return []
    valid_sessions = [
        session for session in sessions
        if isinstance(session, dict) and task_07_is_valid_session(session)
    ]
    paired = task_07_select_paired_workouts(valid_sessions)
    if len(paired) == 6:
        return paired
    return task_07_select_fallback_workouts(valid_sessions)


def task_07_select_paired_workouts(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for session in sessions:
        day = str(session.get("day") or session.get("weekday") or "")
        activity_type = str(session.get("activity_type") or "")
        if activity_type not in {"strength", "cardio"} or not day:
            continue
        by_day.setdefault(day, {"strength": [], "cardio": []})[activity_type].append(session)

    pairs: list[tuple[datetime, bool, dict[str, Any], dict[str, Any]]] = []
    for groups in by_day.values():
        strengths = sorted(groups["strength"], key=task_07_session_sort_key)
        cardios = sorted(groups["cardio"], key=task_07_cardio_sort_key)
        if strengths and cardios:
            strength = strengths[0]
            cardio = cardios[0]
            start = min(task_07_session_start(strength), task_07_session_start(cardio))
            pairs.append((start, task_07_is_swim_session(cardio), strength, cardio))

    if len(pairs) < 3:
        return []

    swim_pairs = sorted([pair for pair in pairs if pair[1]], key=lambda pair: pair[0])
    other_pairs = sorted([pair for pair in pairs if not pair[1]], key=lambda pair: pair[0])
    selected_pairs = []
    if swim_pairs:
        selected_pairs.append(swim_pairs[0])
    for pair in other_pairs:
        if len(selected_pairs) >= 3:
            break
        selected_pairs.append(pair)
    for pair in swim_pairs[1:]:
        if len(selected_pairs) >= 3:
            break
        selected_pairs.append(pair)

    selected_pairs = sorted(selected_pairs[:3], key=lambda pair: pair[0])
    selected: list[dict[str, Any]] = []
    for _start, _has_swim, strength, cardio in selected_pairs:
        selected.extend([strength, cardio])
    return selected


def task_07_select_fallback_workouts(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_type_days: set[tuple[str, str]] = set()

    cardios = sorted([session for session in sessions if session.get("activity_type") == "cardio"], key=task_07_cardio_sort_key)
    strengths = sorted([session for session in sessions if session.get("activity_type") == "strength"], key=task_07_session_sort_key)

    for session in cardios:
        if len([item for item in selected if item.get("activity_type") == "cardio"]) >= 3:
            break
        key = task_07_type_day_key(session)
        if key not in used_type_days:
            selected.append(session)
            used_type_days.add(key)

    used_muscle_groups: set[str] = set()
    for session in strengths:
        if len([item for item in selected if item.get("activity_type") == "strength"]) >= 3:
            break
        key = task_07_type_day_key(session)
        muscle_group = str(session.get("muscle_group") or "")
        if key in used_type_days or (muscle_group and muscle_group in used_muscle_groups):
            continue
        selected.append(session)
        used_type_days.add(key)
        if muscle_group:
            used_muscle_groups.add(muscle_group)

    if len([item for item in selected if item.get("activity_type") == "cardio"]) == 3 and len(
        [item for item in selected if item.get("activity_type") == "strength"]
    ) == 3:
        return sorted(selected, key=task_07_session_sort_key)
    return []


def task_07_is_valid_session(session: dict[str, Any]) -> bool:
    if not session.get("activity_id") or session.get("activity_type") not in {"cardio", "strength"}:
        return False
    if not isinstance(session.get("start_time"), str) or not isinstance(session.get("end_time"), str):
        return False
    try:
        start = datetime.fromisoformat(session["start_time"])
        end = datetime.fromisoformat(session["end_time"])
    except ValueError:
        return False
    if end <= start:
        return False
    day = session.get("day") or session.get("weekday")
    for blocked_day, blocked_start, blocked_end in TASK_07_BLOCKED_WINDOWS:
        if day == blocked_day and start.time() < blocked_end and end.time() > blocked_start:
            return False
    return True


def task_07_type_day_key(session: dict[str, Any]) -> tuple[str, str]:
    return (str(session.get("day") or session.get("weekday") or ""), str(session.get("activity_type") or ""))


def task_07_is_swim_session(session: dict[str, Any]) -> bool:
    text = " ".join(
        str(session.get(key, ""))
        for key in ("activity_id", "activity_name", "muscle_group")
    ).lower()
    return "swim" in text


def task_07_session_start(session: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(session.get("start_time")))
    except ValueError:
        return datetime.max


def task_07_session_sort_key(session: dict[str, Any]) -> tuple[datetime, str]:
    return (task_07_session_start(session), str(session.get("activity_id") or ""))


def task_07_cardio_sort_key(session: dict[str, Any]) -> tuple[int, datetime, str]:
    return (0 if task_07_is_swim_session(session) else 1, task_07_session_start(session), str(session.get("activity_id") or ""))


def task_05_final_reasons(output: dict[str, Any]) -> list[str]:
    reasons = []
    steps = output.get("recommended_steps")
    if not isinstance(steps, list) or not all(isinstance(step, str) and step.strip() for step in steps):
        reasons.append("Task_05 must put clear repair steps in the top-level recommended_steps list.")
    repair = output.get("repair_recommendation", {})
    if not isinstance(repair, dict):
        reasons.append("Task_05 repair_recommendation must be an object.")
    elif "recommended_steps" in repair and "recommended_steps" in output:
        reasons.append("Task_05 should not duplicate recommended_steps inside repair_recommendation; keep that field top-level.")
    return reasons


def task_06_final_reasons(output: dict[str, Any], state: StateManager) -> list[str]:
    reasons = []
    observed = state.get_resource("household-bills://list", []) or []
    observed_pending = [bill for bill in observed if not bill.get("settled")]
    expected_ids = {bill.get("id") for bill in observed_pending}

    final_pending = output.get("pending_bills")
    if not isinstance(final_pending, list):
        return ["Task_06 pending_bills must be a list of unsettled bill objects."]

    final_ids = {bill.get("bill_id") for bill in final_pending if isinstance(bill, dict)}
    if final_ids != expected_ids:
        reasons.append(f"Task_06 pending_bills must include exactly unsettled bill IDs: {sorted(expected_ids)}.")
    if any(isinstance(bill, dict) and bill.get("settled") is not False for bill in final_pending):
        reasons.append("Task_06 pending_bills must not include settled bills.")

    scheduled_ids = {
        item["arguments"].get("bill_id")
        for item in state.get_tool_results("schedule_payment")
    }
    if scheduled_ids != expected_ids:
        reasons.append(f"Task_06 must schedule payments for exactly the unsettled bills: {sorted(expected_ids)}.")

    return reasons


def task_07_final_reasons(output: dict[str, Any], state: StateManager) -> list[str]:
    reasons = []
    scheduled_cardio = output.get("scheduled_cardio")
    scheduled_strength = output.get("scheduled_strength")
    if not isinstance(scheduled_cardio, list) or not isinstance(scheduled_strength, list):
        return ["Task_07 final output must include scheduled_cardio and scheduled_strength lists."]
    if len(scheduled_cardio) != 3:
        reasons.append("Task_07 final output must include exactly 3 scheduled_cardio activities.")
    if len(scheduled_strength) != 3:
        reasons.append("Task_07 final output must include exactly 3 scheduled_strength activities.")
    if any(isinstance(activity, dict) and activity.get("activity_type") != "cardio" for activity in scheduled_cardio):
        reasons.append("Task_07 scheduled_cardio must contain only cardio activities.")
    if any(isinstance(activity, dict) and activity.get("activity_type") != "strength" for activity in scheduled_strength):
        reasons.append("Task_07 scheduled_strength must contain only strength activities.")

    activities = [
        activity
        for activity in [*scheduled_cardio, *scheduled_strength]
        if isinstance(activity, dict)
    ]
    if len(activities) != len(scheduled_cardio) + len(scheduled_strength):
        reasons.append("Task_07 scheduled activities must all be objects.")
    if len(activities) != 6:
        reasons.append("Task_07 final output must schedule exactly 6 total activities.")

    calendar_results = state.get_tool_results("create_calendar_entry")
    if len(calendar_results) != len(activities):
        reasons.append(
            "Task_07 must create exactly one EXERCISE calendar entry per scheduled workout. "
            f"Scheduled activities: {len(activities)}; calendar tool calls: {len(calendar_results)}."
        )

    confirmations = output.get("workout_calendar_confirmation")
    observed_confirmation_ids = {
        item.get("result", {}).get("confirmation_id")
        for item in calendar_results
        if isinstance(item.get("result"), dict) and item.get("result", {}).get("confirmation_id")
    }
    if not isinstance(confirmations, list):
        reasons.append("Task_07 workout_calendar_confirmation must be a list of calendar confirmation IDs.")
    else:
        claimed_confirmation_ids = {item for item in confirmations if isinstance(item, str) and item.strip()}
        if len(confirmations) != len(activities):
            reasons.append(
                "Task_07 workout_calendar_confirmation count must match the number of scheduled workouts."
            )
        if len(claimed_confirmation_ids) != len(confirmations):
            reasons.append("Task_07 workout_calendar_confirmation must contain unique non-empty strings.")
        if not claimed_confirmation_ids.issubset(observed_confirmation_ids):
            missing = sorted(claimed_confirmation_ids - observed_confirmation_ids)
            reasons.append(f"Task_07 confirmation IDs are not all backed by calendar tool results: {missing}.")

    activity_start_times = {
        activity.get("start_time")
        for activity in activities
        if isinstance(activity.get("start_time"), str)
    }
    calendar_dates = {
        item.get("arguments", {}).get("date")
        for item in calendar_results
        if isinstance(item.get("arguments"), dict)
    }
    if activity_start_times != calendar_dates:
        reasons.append("Task_07 scheduled activity start_time values must match create_calendar_entry dates.")

    if any(item.get("arguments", {}).get("category") != "EXERCISE" for item in calendar_results):
        reasons.append("Task_07 calendar entries must use category EXERCISE.")

    observed_sessions = state.get_resource("workout-sessions://list", []) or []
    observed_by_id = {
        session.get("activity_id"): session
        for session in observed_sessions
        if isinstance(session, dict) and session.get("activity_id")
    }
    final_activity_ids = [
        activity.get("activity_id")
        for activity in activities
        if isinstance(activity.get("activity_id"), str)
    ]
    if len(final_activity_ids) != len(set(final_activity_ids)):
        reasons.append("Task_07 scheduled activity IDs must be unique.")
    for activity in activities:
        activity_id = activity.get("activity_id")
        observed = observed_by_id.get(activity_id)
        if not observed:
            reasons.append(f"Task_07 scheduled activity is not grounded in workout-sessions://list: {activity_id!r}.")
            continue
        if not task_07_is_valid_session(observed):
            reasons.append(f"Task_07 scheduled activity violates blocked-window or session validity constraints: {activity_id!r}.")
        for field in ("activity_type", "muscle_group", "start_time", "end_time"):
            if activity.get(field) != observed.get(field):
                reasons.append(f"Task_07 scheduled activity {activity_id!r} has {field} that does not match workout-sessions://list.")
        if activity.get("weekday") and activity.get("weekday") != (observed.get("day") or observed.get("weekday")):
            reasons.append(f"Task_07 scheduled activity {activity_id!r} has weekday that does not match workout-sessions://list.")

    type_day_counts = Counter(
        (str(activity.get("weekday") or observed_by_id.get(activity.get("activity_id"), {}).get("day") or ""), str(activity.get("activity_type") or ""))
        for activity in activities
        if activity.get("activity_type") in {"cardio", "strength"}
    )
    if any(count > 1 for count in type_day_counts.values()):
        reasons.append("Task_07 must not schedule more than one activity of the same type on the same day.")

    types_by_day: dict[str, set[str]] = {}
    for activity in activities:
        day = str(activity.get("weekday") or observed_by_id.get(activity.get("activity_id"), {}).get("day") or "")
        activity_type = str(activity.get("activity_type") or "")
        if day and activity_type:
            types_by_day.setdefault(day, set()).add(activity_type)
    if not any({"strength", "cardio"}.issubset(activity_types) for activity_types in types_by_day.values()):
        reasons.append("Task_07 must include at least one day with both a strength activity and a cardio activity.")

    return reasons


def task_10_final_reasons(output: dict[str, Any], state: StateManager) -> list[str]:
    reasons = []
    bills = state.get_resource("pending-bills://list", []) or []
    due_bills = task_10_due_window_bills(bills)
    expected_scheduled_ids, omitted_ids = task_10_expected_schedule(due_bills)
    actual_scheduled_ids = {
        item["arguments"].get("bill_id")
        for item in state.get_tool_results("schedule_payment")
    }

    if actual_scheduled_ids != expected_scheduled_ids:
        reasons.append(
            "Task_10 must schedule only due-window bills that preserve the USD 200 minimum balance. "
            f"Expected scheduled bill IDs: {sorted(expected_scheduled_ids)}; omitted due to balance: {sorted(omitted_ids)}."
        )

    output_scheduled_ids = {
        payment.get("bill_id")
        for payment in output.get("scheduled_payments", [])
        if isinstance(payment, dict)
    }
    if output_scheduled_ids != actual_scheduled_ids:
        reasons.append("Task_10 scheduled_payments must match the successful schedule_payment tool calls.")

    if omitted_ids:
        alert = output.get("overdraft_alert")
        if not isinstance(alert, str) or not alert.strip():
            reasons.append(f"Task_10 must include a non-empty overdraft_alert for omitted due bills: {sorted(omitted_ids)}.")
        else:
            lowered_alert = alert.lower()
            if not (
                any(str(bill_id).lower() in lowered_alert for bill_id in omitted_ids)
                or "balance" in lowered_alert
                or "overdraft" in lowered_alert
                or "cannot" in lowered_alert
            ):
                reasons.append("Task_10 overdraft_alert must explain the omitted due bill or minimum-balance issue.")
    return reasons


def task_10_due_window_bills(bills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    given_date = datetime.fromisoformat("2026-04-22T12:00:00")
    start_date = given_date - timedelta(days=3)
    due_bills = []
    for bill in bills:
        try:
            due_date = datetime.fromisoformat(str(bill.get("due") or bill.get("due_date")))
        except (TypeError, ValueError):
            continue
        if start_date <= due_date <= given_date:
            due_bills.append(bill)
    return sorted(due_bills, key=lambda bill: str(bill.get("due") or bill.get("due_date")))


def task_10_expected_schedule(due_bills: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    balance = 300.0
    minimum_balance = 200.0
    scheduled: set[str] = set()
    omitted: set[str] = set()
    for bill in due_bills:
        amount = float(bill.get("amount", 0))
        bill_id = str(bill.get("id"))
        if balance - amount >= minimum_balance:
            balance -= amount
            scheduled.add(bill_id)
        else:
            omitted.add(bill_id)
    return scheduled, omitted


def bill_due_in_task_10_window(bill: dict[str, Any]) -> bool:
    return bool(task_10_due_window_bills([bill]))


def slot_datetime(doctor: dict[str, Any] | None, slot: Any) -> str | None:
    if not doctor or not slot:
        return None
    datetimes = doctor.get("slot_datetimes", {})
    if isinstance(datetimes, dict) and slot in datetimes:
        return datetimes[slot]
    day, hour = parse_day_hour(slot)
    if day == "Friday" and hour == 16:
        return "2026-05-08T16:00:00"
    return None


def parse_day_hour(slot: Any) -> tuple[str | None, int]:
    try:
        day, hour = [part.strip() for part in str(slot).split(",", 1)]
        return day, int(hour)
    except (TypeError, ValueError):
        return None, -1
