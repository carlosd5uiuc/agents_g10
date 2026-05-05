from __future__ import annotations

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
from .policy import PolicyEngine
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
            logger.log("mcp_connected", {"resources": available_resources, "tools": available_tools})

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
                    repair_context = "; ".join(decision.reasons)
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
        task_id = summary["task_id"]
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
