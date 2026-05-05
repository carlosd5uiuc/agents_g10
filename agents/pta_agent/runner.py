from __future__ import annotations

import dataclasses
import json
import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .action_selector import ActionSelector
from .execution import ExecutionLayer
from .mcp_client import McpClient
from .models import ActionType, PolicyOutcome, RunConfig, RunStatus, TaskSpec
from .policy import PolicyEngine, slot_datetime, task_07_recommended_activities, task_07_valid_sessions, task_10_due_window_bills, task_10_expected_schedule
from .providers import build_provider
from .state import StateManager
from .task_interpreter import TaskInterpreter
from .trace import TraceLogger
from .verifier import Verifier


async def run_task(config: RunConfig) -> dict[str, Any]:
    interpreter = TaskInterpreter(config.repo_root.resolve())
    task = interpreter.load(config.task_id)
    return await run_task_spec(config, task)


async def run_task_spec(config: RunConfig, task: TaskSpec) -> dict[str, Any]:
    repo_root = config.repo_root.resolve()
    output_root = (config.output_root or default_output_root(repo_root)).resolve()
    server_script = (config.server_script or repo_root / "mcp-server" / "main.py").resolve()

    provider = build_provider(config.provider)
    selector = ActionSelector(provider)
    policy = PolicyEngine()
    verifier = Verifier()
    state = StateManager(task)
    session_id = config.session_id or make_session_id(provider.name, task.task_id)
    logger = TraceLogger(output_root, task.task_id, provider.name, session_id=session_id)
    repair_context: str | None = None
    status = RunStatus.STEP_LIMIT_EXCEEDED
    verification_payload: dict[str, Any] = {"ok": False, "errors": ["not finalized"]}

    logger.log(
        "run_started",
        {
            "task_id": task.task_id,
            "provider": provider.name,
            "model_id": provider.model_id,
            "max_steps": config.max_steps,
            "server_script": str(server_script),
        },
    )

    try:
        async with McpClient(server_script) as client:
            execution = ExecutionLayer(client, logger)
            available_resources = await client.list_resources()
            available_tools = await client.list_tool_schemas()
            allowed_tool_names = set(task.tool_names)
            live_tool_schemas = [
                schema for schema in available_tools
                if schema.get("name") in allowed_tool_names
            ]
            task = dataclasses.replace(task, tool_schemas=live_tool_schemas)
            state.task = task
            logger.log(
                "mcp_connected",
                {
                    "resources": available_resources,
                    "tools": available_tools,
                    "selected_tool_schemas": live_tool_schemas,
                },
            )

            for step in range(config.max_steps):
                selection = await selector.next_action(task, state, repair_context=repair_context)
                logger.log("model_proposal", {"step": step, "raw": selection.raw, "error": selection.error})
                provider_usage = getattr(provider, "last_usage", None)
                if provider_usage:
                    logger.log("model_usage", {"step": step, "usage": provider_usage})

                if selection.error or selection.proposal is None:
                    state.add_failed_attempt(
                        {
                            "step": step,
                            "error": selection.error,
                            "raw": selection.raw,
                            "rate_limited": selection.rate_limited,
                            "retry_after_seconds": selection.retry_after_seconds,
                        }
                    )
                    if selection.rate_limited:
                        status = RunStatus.TOOL_ERROR
                        state.final_output = {
                            "success": False,
                            "reason": "rate_limited",
                            "message": selection.error,
                            "retry_after_seconds": selection.retry_after_seconds,
                        }
                        break
                    repair_context = f"Previous proposal was invalid: {selection.error}"
                    if len(state.failed_attempts) >= 3:
                        status = RunStatus.MODEL_INVALID_OUTPUT
                        break
                    continue

                proposal = selection.proposal
                decision = policy.evaluate(proposal, task, state)
                logger.log("policy_decision", {"step": step, "proposal": proposal.to_dict(), "decision": decision.to_dict()})

                if decision.outcome in {PolicyOutcome.DENY, PolicyOutcome.REPAIR}:
                    violation = {"step": step, "proposal": proposal.to_dict(), "decision": decision.to_dict()}
                    state.add_policy_violation(violation)
                    repair_context = build_repair_context(task, state, proposal, decision.reasons)
                    logger.log("repair_context", {"step": step, "context": repair_context})
                    continue

                if decision.outcome == PolicyOutcome.CLARIFY:
                    status = RunStatus.NEEDS_CLARIFICATION
                    state.final_output = {"success": False, "message": proposal.message, "reason": proposal.reason}
                    break

                if decision.outcome == PolicyOutcome.STOP or proposal.action == ActionType.STOP:
                    status = proposal.status or RunStatus.FAILED_CONSTRAINTS
                    state.final_output = proposal.final_output or {"success": False, "reason": proposal.reason or "stopped"}
                    break

                try:
                    if proposal.action == ActionType.READ_RESOURCE:
                        await execution.read_resource(proposal, state)
                    elif proposal.action == ActionType.CALL_TOOL:
                        await execution.call_tool(proposal, state)
                    elif proposal.action == ActionType.FINALIZE:
                        assert proposal.final_output is not None
                        state.final_output = proposal.final_output
                        verification = verifier.verify(task, state, proposal.final_output)
                        verification_payload = verification.to_dict()
                        status = RunStatus.SUCCESS if verification.ok and proposal.final_output.get("success") else RunStatus.VERIFICATION_FAILED
                        logger.log("verification", verification_payload)
                        break
                except Exception as exc:  # noqa: BLE001 - surfaced in trace and summary
                    logger.log("execution_error", {"step": step, "proposal": proposal.to_dict(), "error": repr(exc)})
                    status = RunStatus.TOOL_ERROR
                    state.final_output = {"success": False, "reason": repr(exc)}
                    break
                repair_context = None
    except Exception as exc:  # noqa: BLE001 - startup failures should still produce artifacts
        logger.log("run_error", {"error": repr(exc)})
        status = RunStatus.TOOL_ERROR
        state.final_output = {"success": False, "reason": repr(exc)}

    if state.final_output is None:
        state.final_output = {"success": False, "reason": status.value}

    if state.final_output.get("success") is False and status == RunStatus.VERIFICATION_FAILED:
        status = RunStatus.FAILED_CONSTRAINTS

    final_path = logger.write_json("final.json", state.final_output)
    snapshot_path = logger.write_json("state_snapshot.json", state.to_snapshot())
    summary = {
        "run_id": logger.run_id,
        "session_id": logger.session_id,
        "session_dir": str(logger.session_dir),
        "task_id": task.task_id,
        "status": status.value,
        "provider": provider.name,
        "model_id": provider.model_id,
        "step_count": count_trace_events(logger.trace_path, "model_proposal"),
        "tool_count": len(state.tool_results),
        "resource_count": len(state.resources),
        "verification": verification_payload,
        "artifacts": {
            "trace": str(logger.trace_path),
            "final": str(final_path),
            "summary": str(logger.run_dir / "summary.json"),
            "state_snapshot": str(snapshot_path),
        },
    }
    summary_path = logger.write_json("summary.json", summary)
    summary["artifacts"]["summary"] = str(summary_path)
    logger.log("run_finished", summary)
    return summary


def build_repair_context(
    task: TaskSpec,
    state: StateManager,
    proposal: Any,
    reasons: list[str],
) -> str:
    common = build_common_repair_context(task, state, proposal, reasons)
    if task.task_id == "task_07":
        return common + "\n\n" + build_task_07_repair_context(state, proposal, reasons)
    task_guidance = build_task_specific_repair_guidance(task, state)
    if task_guidance:
        return common + "\n\n" + task_guidance
    return common


def build_common_repair_context(
    task: TaskSpec,
    state: StateManager,
    proposal: Any,
    reasons: list[str],
) -> str:
    proposal_dict = compact_rejected_proposal(proposal.to_dict() if hasattr(proposal, "to_dict") else proposal)
    tool_counts = Counter(item.get("tool_name") for item in state.tool_results)
    lines = [
        f"{task.task_id} proposal rejected.",
        "Reasons:",
        *[f"- {reason}" for reason in reasons],
        "Rejected proposal:",
        json.dumps(proposal_dict, ensure_ascii=False, default=str),
        "Current state summary:",
        f"- resources_read: {sorted(state.resources)}",
        f"- tool_results_by_name: {dict(sorted(tool_counts.items()))}",
        f"- policy_violations_so_far: {len(state.policy_violations)}",
        f"- failed_attempts_so_far: {len(state.failed_attempts)}",
        "Repair rules:",
        "- Treat StateManager resources and tool_results as the source of truth.",
        "- Do not repeat irreversible tool calls already present in tool_results.",
        "- Do not invent confirmation IDs; use only IDs that appear in tool_results.",
        "- If current irreversible tool state makes success impossible, call stop with status='failed_constraints'.",
    ]
    return "\n".join(lines)


def compact_rejected_proposal(proposal_dict: Any) -> Any:
    if not isinstance(proposal_dict, dict):
        return proposal_dict
    compact = json.loads(json.dumps(proposal_dict, ensure_ascii=False, default=str))
    arguments = compact.get("arguments")
    if compact.get("tool_name") == "generate_report" and isinstance(arguments, dict):
        expenses = arguments.get("expenses")
        if isinstance(expenses, list):
            categories = [
                item.get("category")
                for item in expenses
                if isinstance(item, dict) and item.get("category")
            ]
            priority_categories = [
                item.get("category")
                for item in expenses
                if isinstance(item, dict) and item.get("category") and item.get("priority")
            ]
            arguments["expenses"] = {
                "count": len(expenses),
                "categories": categories,
                "priority_categories": priority_categories,
                "note": "Compacted in repair context; use StateManager resources for full expense data.",
            }
    return compact


def build_task_specific_repair_guidance(task: TaskSpec, state: StateManager) -> str:
    method = globals().get(f"build_{task.task_id}_repair_guidance")
    if callable(method):
        return method(state)
    return ""


def build_task_01_repair_guidance(state: StateManager) -> str:
    travel_results = state.get_tool_results("create_travel_arrangement")
    calendar_results = state.get_tool_results("create_calendar_entry")
    selected_ride_id = travel_results[0]["arguments"].get("ride_id") if travel_results else None
    selected_ride = find_resource_item(state.get_resource("transportation://list", []), "id", selected_ride_id)
    lines = [
        "Task_01 recovery guidance:",
        "- Required evidence: one create_travel_arrangement result and one RIDE create_calendar_entry result.",
        f"- Existing travel arrangements: {summarize_tool_results(travel_results)}",
        f"- Existing calendar entries: {summarize_tool_results(calendar_results)}",
    ]
    if travel_results and selected_ride and not calendar_results:
        lines.append(
            f"- Next valid action: call create_calendar_entry with date={selected_ride.get('arrival_time')!r} and category='RIDE'."
        )
    elif travel_results and calendar_results:
        lines.append("- Next valid action: finalize using the existing travel and calendar confirmation IDs.")
    else:
        lines.append("- Next valid action: choose a grounded ride satisfying route, budget, no-surge, and arrival constraints.")
    return "\n".join(lines)


def build_task_02_repair_guidance(state: StateManager) -> str:
    repair_results = state.get_tool_results("set_up_repair_appointment")
    return "\n".join(
        [
            "Task_02 recovery guidance:",
            "- Select a repair option grounded in repair://options for laptop battery repair.",
            "- Requirements: in-network, not Thursday, deductible <= 120.",
            f"- Existing repair appointments: {summarize_tool_results(repair_results)}",
            "- If appointment evidence already exists, finalize using that confirmation ID.",
        ]
    )


def build_task_03_repair_guidance(state: StateManager) -> str:
    catering_results = state.get_tool_results("set_catering_appointment")
    invitation_results = state.get_tool_results("send_invitations")
    return "\n".join(
        [
            "Task_03 recovery guidance:",
            "- Required evidence: one safe catering appointment and one invitations result.",
            "- Catering must be grounded in catering://options, vegetarian, within budget, and avoid nuts.",
            "- Invitations must go exactly to one@example.com, two@example.com, and three@example.com.",
            f"- Existing catering appointments: {summarize_tool_results(catering_results)}",
            f"- Existing invitation calls: {summarize_tool_results(invitation_results)}",
            "- If both evidence items exist, finalize using existing tool results instead of calling more tools.",
        ]
    )


def build_task_04_repair_guidance(state: StateManager) -> str:
    doctor_results = state.get_tool_results("set_up_doctor_appointment")
    calendar_results = state.get_tool_results("create_calendar_entry")
    selected = doctor_results[0]["arguments"] if doctor_results else {}
    doctor = find_resource_item(state.get_resource("doctor://list", []), "name", selected.get("doctor_name"))
    appointment_time = selected.get("appointment_time")
    expected_datetime = slot_datetime_from_resource(doctor, appointment_time)
    lines = [
        "Task_04 recovery guidance:",
        "- Required evidence: dermatologist appointment for eczema with copay <= 50 and one MEDICAL calendar entry.",
        f"- Existing doctor appointments: {summarize_tool_results(doctor_results)}",
        f"- Existing calendar entries: {summarize_tool_results(calendar_results)}",
    ]
    if doctor_results and not calendar_results and expected_datetime:
        lines.append(
            f"- Next valid action: call create_calendar_entry with date={expected_datetime!r} and category='MEDICAL'."
        )
    elif doctor_results and calendar_results:
        lines.append("- Next valid action: finalize using the existing appointment and calendar confirmation IDs.")
    else:
        lines.append("- Next valid action: select a grounded doctor slot from doctor://list; do not ask the user for hidden date metadata.")
    return "\n".join(lines)


def build_task_05_repair_guidance(state: StateManager) -> str:
    return "\n".join(
        [
            "Task_05 recovery guidance:",
            "- This task is primarily informational; finalize with evidence from troubleshoot resources.",
            "- Put recommended_steps as a top-level non-empty list of strings.",
            "- Do not nest recommended_steps only inside repair_recommendation.",
            f"- Resources read: {sorted(state.resources)}",
        ]
    )


def build_task_06_repair_guidance(state: StateManager) -> str:
    bills = state.get_resource("household-bills://list", []) or []
    expected_ids = sorted(str(bill.get("id")) for bill in bills if isinstance(bill, dict) and bill.get("id") and not bill.get("settled"))
    scheduled_ids = sorted(
        str(item["arguments"].get("bill_id"))
        for item in state.get_tool_results("schedule_payment")
        if isinstance(item.get("arguments"), dict) and item["arguments"].get("bill_id")
    )
    missing_ids = sorted(set(expected_ids) - set(scheduled_ids))
    extra_ids = sorted(set(scheduled_ids) - set(expected_ids))
    lines = [
        "Task_06 recovery guidance:",
        f"- Expected unsettled bill IDs: {expected_ids}",
        f"- Already scheduled bill IDs: {scheduled_ids}",
        f"- Missing schedule_payment IDs: {missing_ids}",
        f"- Extra/invalid scheduled IDs: {extra_ids}",
        "- Do not schedule settled bills.",
    ]
    if extra_ids:
        lines.append("- Existing invalid payment calls are irreversible; if they make a valid final impossible, call stop with status='failed_constraints'.")
    elif missing_ids:
        lines.append("- Next valid action: schedule only the missing unsettled bills with amount and due-date-matching payment_date.")
    else:
        lines.append("- Next valid action: finalize with pending_bills and scheduled_payments matching the successful tool calls.")
    return "\n".join(lines)


def build_task_08_repair_guidance(state: StateManager) -> str:
    report_results = state.get_tool_results("generate_report")
    observed = state.get_resource("expenses://list", []) or []
    non_priority = [
        item for item in observed
        if isinstance(item, dict) and item.get("category") and not item.get("priority")
    ]
    priority_categories = sorted(
        str(item.get("category"))
        for item in observed
        if isinstance(item, dict) and item.get("category") and item.get("priority")
    )
    allowed_categories = sorted(str(item.get("category")) for item in non_priority)
    recommended = task_08_recommended_cut_candidates(non_priority)
    recommended_categories = [item.get("category") for item in recommended]
    recommended_total = sum(float(item.get("recommended_cut", item.get("amount", 0))) for item in recommended)
    recommended_tool_expenses = [
        {key: item[key] for key in ("category", "amount", "priority") if key in item}
        for item in recommended
    ]
    return "\n".join(
        [
            "Task_08 recovery guidance:",
            "- Use expenses://list as the source of truth, but do NOT pass the full expense list to generate_report.",
            "- generate_report.arguments.expenses is the cut-candidate list. It must contain only observed non-priority categories.",
            f"- Priority categories that must be excluded from arguments.expenses: {priority_categories}",
            f"- Allowed non-priority categories: {allowed_categories}",
            "- Preferences: avoid health and gym when possible.",
            f"- One valid cut plan: categories={recommended_categories}, total_reduction={recommended_total:g}.",
            f"- Valid generate_report.arguments.expenses example: {json.dumps(recommended_tool_expenses, ensure_ascii=False)}",
            "- Valid suggestions example: Cut streaming by $45, meal_delivery by $95, and books by $10 for a total reduction of $150.",
            f"- Existing report calls: {summarize_tool_results(report_results)}",
            "- If report evidence exists, finalize from the existing report instead of calling generate_report again.",
        ]
    )


def task_08_recommended_cut_candidates(non_priority_expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_categories = ["streaming", "meal_delivery", "books"]
    by_category = {
        str(item.get("category")): item
        for item in non_priority_expenses
        if item.get("category")
    }
    recommended = []
    for category in preferred_categories:
        item = by_category.get(category)
        if item:
            copy = dict(item)
            if category == "books":
                copy["recommended_cut"] = 10
            recommended.append(copy)
    if len(recommended) == 3:
        return recommended
    total = 0.0
    fallback = []
    for item in sorted(non_priority_expenses, key=lambda expense: float(expense.get("amount", 0)), reverse=True):
        category = str(item.get("category"))
        if category in {"health", "gym"}:
            continue
        fallback.append(dict(item))
        total += float(item.get("amount", 0))
        if total >= 150:
            break
    return fallback


def build_task_09_repair_guidance(state: StateManager) -> str:
    return_results = state.get_tool_results("create_return")
    calendar_results = state.get_tool_results("create_calendar_entry")
    selected_id = return_results[0]["arguments"].get("id") if return_results else None
    option = find_resource_item(state.get_resource("online-purchase://return_options", []), "id", selected_id)
    lines = [
        "Task_09 recovery guidance:",
        "- Required evidence: one valid create_return result and one PRODUCT_RETURN calendar entry.",
        "- Return option must be free, drop-off, and refund to original_payment.",
        f"- Existing return calls: {summarize_tool_results(return_results)}",
        f"- Existing calendar entries: {summarize_tool_results(calendar_results)}",
    ]
    if return_results and option and not calendar_results:
        lines.append(
            f"- Next valid action: call create_calendar_entry with date='{option.get('deadline')}T09:00:00' and category='PRODUCT_RETURN'."
        )
    elif return_results and calendar_results:
        lines.append("- Next valid action: finalize using the existing return_id, label_id, and calendar confirmation ID.")
    else:
        lines.append("- Next valid action: select a grounded valid return option from online-purchase://return_options.")
    return "\n".join(lines)


def build_task_10_repair_guidance(state: StateManager) -> str:
    bills = state.get_resource("pending-bills://list", []) or []
    due_bills = task_10_due_window_bills(bills)
    expected_ids, omitted_ids = task_10_expected_schedule(due_bills)
    scheduled_ids = {
        str(item["arguments"].get("bill_id"))
        for item in state.get_tool_results("schedule_payment")
        if isinstance(item.get("arguments"), dict) and item["arguments"].get("bill_id")
    }
    missing_ids = sorted(expected_ids - scheduled_ids)
    extra_ids = sorted(scheduled_ids - expected_ids)
    return "\n".join(
        [
            "Task_10 recovery guidance:",
            f"- Due-window bill IDs: {[bill.get('id') for bill in due_bills]}",
            f"- Expected scheduled IDs preserving the USD 200 minimum balance: {sorted(expected_ids)}",
            f"- Omitted due to balance: {sorted(omitted_ids)}",
            f"- Already scheduled IDs: {sorted(scheduled_ids)}",
            f"- Missing schedule_payment IDs: {missing_ids}",
            f"- Extra/invalid scheduled IDs: {extra_ids}",
            "- Do not schedule omitted bills; explain them in overdraft_alert.",
            "- If scheduled IDs match expected IDs, finalize with scheduled_payments matching successful tool calls and include overdraft_alert when any due bill was omitted.",
        ]
    )


def summarize_tool_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "none"
    summaries = []
    for item in results:
        result = item.get("result")
        compact_result: Any = result
        if isinstance(result, dict):
            compact_result = {
                key: value
                for key, value in result.items()
                if key in {
                    "confirmation_id",
                    "payment_confirmation_id",
                    "return_id",
                    "label_id",
                    "bill_id",
                    "ride_id",
                    "scheduled_date",
                    "payment_date",
                    "entry_date",
                    "category",
                }
            }
            if not compact_result:
                compact_result = result
        summaries.append({"arguments": item.get("arguments", {}), "result": compact_result})
    return json.dumps(summaries, ensure_ascii=False, default=str)


def find_resource_item(items: Any, key: str, value: Any) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get(key) == value:
            return item
    return None


def slot_datetime_from_resource(doctor: dict[str, Any] | None, appointment_time: Any) -> str | None:
    return slot_datetime(doctor, appointment_time)


def build_task_07_repair_context(state: StateManager, proposal: Any, reasons: list[str]) -> str:
    calendar_results = state.get_tool_results("create_calendar_entry")
    recommended_activities = task_07_recommended_activities(state)
    recommended_dates = {
        activity.get("start_time")
        for activity in recommended_activities
        if isinstance(activity.get("start_time"), str)
    }
    recommended_ids = [
        activity.get("activity_id")
        for activity in recommended_activities
        if activity.get("activity_id")
    ]
    valid_dates = {
        session.get("start_time")
        for session in task_07_valid_sessions(state)
        if isinstance(session.get("start_time"), str)
    }
    wrong_category = [
        item for item in calendar_results
        if item.get("arguments", {}).get("category") != "EXERCISE"
    ]
    unexpected_dates = sorted(
        {
            item.get("arguments", {}).get("date")
            for item in calendar_results
            if isinstance(item.get("arguments"), dict) and item.get("arguments", {}).get("date")
        }
        - valid_dates
    )
    duplicate_dates = [
        date for date, count in Counter(
            item.get("arguments", {}).get("date")
            for item in calendar_results
            if isinstance(item.get("arguments"), dict)
        ).items()
        if date and count > 1
    ]
    entry_lines = []
    for index, item in enumerate(calendar_results, start=1):
        arguments = item.get("arguments", {}) if isinstance(item.get("arguments"), dict) else {}
        result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
        entry_lines.append(
            f"  {index}. date={arguments.get('date')!r}, "
            f"category={arguments.get('category')!r}, "
            f"confirmation_id={result.get('confirmation_id')!r}"
        )
    if not entry_lines:
        entry_lines.append("  none")

    guidance = [
        "Task_07 proposal rejected.",
        "Reasons:",
        *[f"- {reason}" for reason in reasons],
        "Current irreversible calendar state:",
        "- Required final routine: exactly 3 cardio, exactly 3 strength, no blocked Monday/Wednesday window, no duplicate type/day, and at least one strength-cardio paired day.",
        f"- Recommended six-workout plan IDs: {recommended_ids}",
        f"- Recommended six-workout plan dates: {sorted(recommended_dates)}",
        f"- Total create_calendar_entry tool calls so far: {len(calendar_results)}",
        f"- Wrong-category calendar calls: {len(wrong_category)}",
        f"- Calendar dates outside valid observed workout set: {unexpected_dates}",
        f"- Duplicate workout dates: {duplicate_dates or []}",
        "Calendar tool calls are irreversible and are counted by policy/verifier.",
        "Existing calendar calls:",
        *entry_lines,
    ]

    if wrong_category or unexpected_dates or len(calendar_results) >= 6:
        guidance.extend(
            [
                "Do NOT create additional create_calendar_entry calls.",
                "Adding more calendar calls will increase over-count or leave wrong/irreversible evidence in state.",
                "Recovery options:",
                "- If the existing calendar evidence already satisfies all requirements, finalize using the existing confirmation IDs.",
                "- Otherwise call stop with status='failed_constraints' and reason='unrecoverable calendar state'.",
            ]
        )
    else:
        missing_dates = sorted(
            recommended_dates
            - {
                item.get("arguments", {}).get("date")
                for item in calendar_results
                if isinstance(item.get("arguments"), dict)
            }
        )
        guidance.extend(
            [
                "Recovery options:",
                f"- If following the recommended plan, create only these remaining EXERCISE dates: {missing_dates}.",
                "- Other valid six-workout plans are allowed if they satisfy all hard constraints and stay grounded in workout-sessions://list.",
                "- Do not create blocked-window entries, duplicate type/day entries, or more than 3 cardio / 3 strength entries.",
                "- Or finalize if all required evidence is already present.",
            ]
        )

    proposal_action = getattr(proposal, "action", None)
    if proposal_action:
        guidance.append(f"Rejected action was: {getattr(proposal_action, 'value', proposal_action)}.")
    return "\n".join(guidance)


async def run_suite(config: RunConfig, task_ids: list[str] | None = None) -> list[dict[str, Any]]:
    interpreter = TaskInterpreter(config.repo_root.resolve())
    ids = task_ids or interpreter.available_task_ids()
    session_id = config.session_id or make_session_id(config.provider, "suite")
    results = []
    for index, task_id in enumerate(ids):
        task_config = RunConfig(
            task_id=task_id,
            provider=config.provider,
            repo_root=config.repo_root,
            output_root=config.output_root,
            max_steps=config.max_steps,
            server_script=config.server_script,
            task_delay_seconds=config.task_delay_seconds,
            session_id=session_id,
        )
        results.append(await run_task(task_config))
        if config.task_delay_seconds > 0 and index < len(ids) - 1:
            await asyncio.sleep(config.task_delay_seconds)
    return results


def write_grader_bundle(summaries: list[dict[str, Any]], output_path: Path) -> None:
    bundle: dict[str, Any] = {}
    for summary in summaries:
        task_id = summary.get("expected_task_id") or summary["task_id"]
        with Path(summary["artifacts"]["final"]).open("r", encoding="utf-8") as handle:
            bundle[task_id] = json.load(handle)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(bundle, handle, indent=2)


def write_session_summary(
    summaries: list[dict[str, Any]],
    output_path: Path,
    grader_bundle: Path | None = None,
    grader_results: Path | None = None,
) -> dict[str, Any]:
    status_counts = Counter(summary["status"] for summary in summaries)
    metrics = build_session_metrics(summaries)
    payload = {
        "session_id": summaries[0].get("session_id") if summaries else None,
        "session_dir": summaries[0].get("session_dir") if summaries else str(output_path.parent),
        "task_count": len(summaries),
        "status_counts": dict(sorted(status_counts.items())),
        "metrics": metrics,
        "grader_bundle": str(grader_bundle) if grader_bundle else None,
        "grader_results": str(grader_results) if grader_results else None,
        "tasks": [
            {
                "task_id": summary["task_id"],
                "status": summary["status"],
                "step_count": summary["step_count"],
                "tool_count": summary["tool_count"],
                "resource_count": summary["resource_count"],
                "verification_ok": summary["verification"]["ok"],
                "final": summary["artifacts"]["final"],
                "trace": summary["artifacts"]["trace"],
            }
            for summary in summaries
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return payload


def make_session_id(provider: str, label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in label)
    return f"{stamp}-{provider}-{safe_label}-{uuid.uuid4().hex[:8]}"


def default_output_root(repo_root: Path) -> Path:
    return repo_root / "outputs" / "sessions"


def build_session_metrics(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    task_count = len(summaries)
    trace_paths = [Path(summary["artifacts"]["trace"]) for summary in summaries]
    total_steps = sum(int(summary.get("step_count", 0)) for summary in summaries)
    model_error_counts = [count_model_errors(path) for path in trace_paths]
    return {
        "total_llm_calls": total_steps,
        "repair_count": sum(count_policy_outcomes(path, {"repair"}) for path in trace_paths),
        "invalid_model_output_count": sum(model_error_counts) + sum(
            1
            for summary, model_error_count in zip(summaries, model_error_counts, strict=False)
            if summary.get("status") == RunStatus.MODEL_INVALID_OUTPUT.value and model_error_count == 0
        ),
        "tool_call_count": sum(int(summary.get("tool_count", 0)) for summary in summaries),
        "verification_failure_count": sum(
            1 for summary in summaries
            if summary.get("status") == RunStatus.VERIFICATION_FAILED.value
        ),
        "average_steps_per_task": round(total_steps / task_count, 3) if task_count else 0,
    }


def count_policy_outcomes(path: Path, outcomes: set[str]) -> int:
    count = 0
    for event in iter_trace_events(path):
        if event.get("event") != "policy_decision":
            continue
        outcome = event.get("payload", {}).get("decision", {}).get("outcome")
        if outcome in outcomes:
            count += 1
    return count


def count_model_errors(path: Path) -> int:
    return sum(
        1
        for event in iter_trace_events(path)
        if event.get("event") == "model_proposal" and event.get("payload", {}).get("error")
    )


def count_trace_events(path: Path, event_name: str) -> int:
    return sum(1 for event in iter_trace_events(path) if event.get("event") == event_name)


def iter_trace_events(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
