from __future__ import annotations

import json
import os
import subprocess
import sys
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import RunStatus, TaskSpec
from .providers import AnthropicProvider, load_dotenv
from .runner import default_output_root, make_session_id
from .task_interpreter import TaskInterpreter
from .trace import TraceLogger, scrub_secrets


DEFAULT_OPENCLAW_DELAY_SECONDS = 10.0
DEFAULT_OPENCLAW_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class OpenClawRunConfig:
    repo_root: Path
    task_id: str = "task_01"
    output_root: Path | None = None
    model_id: str | None = None
    timeout_seconds: int = DEFAULT_OPENCLAW_TIMEOUT_SECONDS
    task_delay_seconds: float = DEFAULT_OPENCLAW_DELAY_SECONDS
    session_id: str | None = None


def setup_openclaw_baseline(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    package_dir = openclaw_package_dir(repo_root)
    package_dir.mkdir(parents=True, exist_ok=True)
    ensure_openclaw_config(repo_root)

    install = subprocess.run(
        [npm_executable(), "--prefix", str(package_dir), "install"],
        cwd=str(repo_root),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=600,
        check=False,
    )
    configured = False
    mcp_result: subprocess.CompletedProcess[str] | None = None
    if install.returncode == 0:
        mcp_result = register_openclaw_mcp(repo_root)
        configured = mcp_result.returncode == 0

    return {
        "package_dir": str(package_dir),
        "state_dir": str(openclaw_state_dir(repo_root)),
        "config_path": str(openclaw_config_path(repo_root)),
        "install_returncode": install.returncode,
        "install_stdout": install.stdout[-2000:],
        "install_stderr": install.stderr[-2000:],
        "mcp_configured": configured,
        "mcp_returncode": mcp_result.returncode if mcp_result else None,
        "mcp_stdout": mcp_result.stdout[-2000:] if mcp_result else "",
        "mcp_stderr": mcp_result.stderr[-2000:] if mcp_result else "",
    }


async def run_openclaw_task(config: OpenClawRunConfig) -> dict[str, Any]:
    repo_root = config.repo_root.resolve()
    output_root = (config.output_root or default_output_root(repo_root)).resolve()
    task = TaskInterpreter(repo_root).load(config.task_id)
    model_id = config.model_id or current_openclaw_model_id()
    model_label = compact_openclaw_model_label(model_id)
    session_id = config.session_id or make_session_id("openclaw", session_label(task.task_id, model_label))
    logger = TraceLogger(output_root, task.task_id, "openclaw", session_id=session_id)
    ensure_openclaw_config(repo_root)

    logger.log(
        "run_started",
        {
            "task_id": task.task_id,
            "provider": "openclaw",
            "model_id": model_id,
            "package_dir": str(openclaw_package_dir(repo_root)),
            "config_path": str(openclaw_config_path(repo_root)),
        },
    )

    final_output: dict[str, Any]
    status = RunStatus.TOOL_ERROR
    verification = {"ok": False, "errors": ["OpenClaw baseline output was not parsed."]}
    command: list[str] = []
    returncode: int | None = None
    stdout = ""
    stderr = ""
    inferred_llm_calls = 0
    inferred_tool_calls = 0
    openclaw_metrics: dict[str, Any] = {}

    if not openclaw_local_binary_exists(repo_root):
        final_output = {
            "success": False,
            "reason": "openclaw_not_installed",
            "message": "Run `uv run pta setup-openclaw` before running the OpenClaw baseline.",
        }
        logger.log("setup_missing", {"package_dir": str(openclaw_package_dir(repo_root))})
    else:
        register = register_openclaw_mcp(repo_root)
        logger.log(
            "mcp_registered",
            {
                "returncode": register.returncode,
                "stdout": register.stdout[-2000:],
                "stderr": register.stderr[-2000:],
            },
        )
        if register.returncode != 0:
            final_output = {
                "success": False,
                "reason": "openclaw_mcp_registration_failed",
                "message": register.stderr[-1000:] or register.stdout[-1000:],
            }
        else:
            command = build_openclaw_agent_command(
                repo_root=repo_root,
                task=task,
                model_id=model_id,
                timeout_seconds=config.timeout_seconds,
                openclaw_session_id=logger.run_id,
            )
            logger.log("openclaw_command_started", {"command": redact_command(command)})
            completed = subprocess.run(
                command,
                cwd=str(repo_root),
                env=openclaw_environment(repo_root),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=config.timeout_seconds + 60,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            (logger.run_dir / "openclaw_stdout.txt").write_text(stdout, encoding="utf-8", errors="replace")
            (logger.run_dir / "openclaw_stderr.txt").write_text(stderr, encoding="utf-8", errors="replace")
            logger.log(
                "openclaw_command_finished",
                {
                    "returncode": returncode,
                    "stdout_tail": stdout[-4000:],
                    "stderr_tail": stderr[-4000:],
                },
            )
            openclaw_metrics = extract_openclaw_session_metrics(repo_root, logger.run_id, stdout)
            inferred_llm_calls = int(openclaw_metrics.get("model_call_count") or infer_llm_call_count(stdout) or (1 if returncode == 0 else 0))
            inferred_tool_calls = int(openclaw_metrics.get("tool_call_count") or infer_tool_call_count(stdout))
            if returncode != 0:
                final_output = {
                    "success": False,
                    "reason": "openclaw_command_failed",
                    "message": stderr[-1000:] or stdout[-1000:],
                }
            else:
                try:
                    final_output = extract_final_json(stdout)
                    status = RunStatus.SUCCESS if final_output.get("success") else RunStatus.FAILED_CONSTRAINTS
                    verification = {"ok": bool(final_output.get("success")), "errors": [] if final_output.get("success") else ["success=false"]}
                except ValueError as exc:
                    final_output = {
                        "success": False,
                        "reason": "openclaw_output_parse_error",
                        "message": str(exc),
                    }
                    status = RunStatus.MODEL_INVALID_OUTPUT
                    verification = {"ok": False, "errors": [str(exc)]}
                    logger.log("parse_error", {"error": str(exc)})

    final_path = logger.write_json("final.json", final_output)
    metrics_path = logger.write_json("openclaw_metrics.json", openclaw_metrics)
    snapshot_path = logger.write_json(
        "state_snapshot.json",
        {
            "provider": "openclaw",
            "model_id": model_id,
            "command": redact_command(command),
            "returncode": returncode,
            "stdout_path": str(logger.run_dir / "openclaw_stdout.txt"),
            "stderr_path": str(logger.run_dir / "openclaw_stderr.txt"),
            "openclaw_metrics": openclaw_metrics,
        },
    )
    summary = {
        "run_id": logger.run_id,
        "session_id": logger.session_id,
        "session_dir": str(logger.session_dir),
        "task_id": task.task_id,
        "status": status.value,
        "provider": "openclaw",
        "model_id": model_id,
        "step_count": inferred_llm_calls,
        "tool_count": inferred_tool_calls,
        "resource_count": 0,
        "verification": verification,
        "artifacts": {
            "trace": str(logger.trace_path),
            "final": str(final_path),
            "summary": str(logger.run_dir / "summary.json"),
            "state_snapshot": str(snapshot_path),
            "openclaw_metrics": str(metrics_path),
        },
    }
    summary_path = logger.write_json("summary.json", summary)
    summary["artifacts"]["summary"] = str(summary_path)
    logger.log("run_finished", summary)
    return summary


async def run_openclaw_suite(config: OpenClawRunConfig, task_ids: list[str] | None = None) -> list[dict[str, Any]]:
    interpreter = TaskInterpreter(config.repo_root.resolve())
    ids = task_ids or interpreter.available_task_ids()
    model_id = config.model_id or current_openclaw_model_id()
    session_id = config.session_id or make_session_id(
        "openclaw",
        session_label("run-all", compact_openclaw_model_label(model_id)),
    )
    results = []
    for index, task_id in enumerate(ids):
        results.append(
            await run_openclaw_task(
                OpenClawRunConfig(
                    repo_root=config.repo_root,
                    task_id=task_id,
                    output_root=config.output_root,
                    model_id=model_id,
                    timeout_seconds=config.timeout_seconds,
                    task_delay_seconds=config.task_delay_seconds,
                    session_id=session_id,
                )
            )
        )
        if config.task_delay_seconds > 0 and index < len(ids) - 1:
            await asyncio.sleep(config.task_delay_seconds)
    return results


def build_openclaw_agent_command(
    repo_root: Path,
    task: TaskSpec,
    model_id: str,
    timeout_seconds: int,
    openclaw_session_id: str,
) -> list[str]:
    return [
        npm_executable(),
        "--prefix",
        str(openclaw_package_dir(repo_root)),
        "exec",
        "--",
        "openclaw",
        "agent",
        "--local",
        "--session-id",
        openclaw_session_id,
        "--model",
        openclaw_model_arg(model_id),
        "--message",
        build_openclaw_message(task),
        "--timeout",
        str(timeout_seconds),
        "--json",
    ]


def build_openclaw_message(task: TaskSpec) -> str:
    return json.dumps(
        {
            "role": "stock_openclaw_baseline",
            "benchmark_rules": [
                "Use only the configured pta-benchmark MCP environment.",
                "Do not inspect repository files, grader code, prior outputs, or expected answers.",
                "Read the listed MCP resources before selecting irreversible actions.",
                "If native MCP resources are not directly available, call pta-benchmark__read_benchmark_resource with the resource URI.",
                "Call MCP benchmark tools directly when action is required.",
                "Do not use the PTA action proposal schema.",
                "When finished, reply with exactly one JSON object matching output_structure and no markdown.",
            ],
            "task": {
                "task_id": task.task_id,
                "prompt": task.prompt,
                "hard_constraints": task.hard_constraints,
                "preferences": task.preferences,
                "behavior_checklist": task.behavior_checklist,
                "resource_uris": task.resource_uris,
                "tool_names": task.tool_names,
                "tool_schemas": task.tool_schemas,
                "output_structure": task.output_structure,
            },
        },
        ensure_ascii=False,
        default=str,
    )


def register_openclaw_mcp(repo_root: Path) -> subprocess.CompletedProcess[str]:
    ensure_openclaw_config(repo_root)
    server_config = {
        "command": "uv",
        "args": ["run", "python", "main.py"],
        "cwd": str((repo_root / "mcp-server").resolve()),
    }
    return subprocess.run(
        [
            npm_executable(),
            "--prefix",
            str(openclaw_package_dir(repo_root)),
            "exec",
            "--",
            "openclaw",
            "mcp",
            "set",
            "pta-benchmark",
            json.dumps(server_config),
        ],
        cwd=str(repo_root),
        env=openclaw_environment(repo_root),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )


def ensure_openclaw_config(repo_root: Path) -> None:
    state_dir = openclaw_state_dir(repo_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = openclaw_config_path(repo_root)
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {}
    agent_defaults = config.setdefault("agents", {}).setdefault("defaults", {})
    agent_defaults["workspace"] = str(state_dir / "workspace")
    agent_defaults["skipBootstrap"] = True
    agent_defaults["skills"] = []
    config.setdefault("tools", {})
    config["tools"]["profile"] = "coding"
    deny = set(config["tools"].get("deny", []))
    deny.update(
        {
            "browser",
            "canvas",
            "cron",
            "edit",
            "exec",
            "group:agents",
            "group:automation",
            "group:fs",
            "group:memory",
            "group:media",
            "group:messaging",
            "group:runtime",
            "group:sessions",
            "group:ui",
            "group:web",
            "process",
            "read",
            "write",
        }
    )
    config["tools"]["deny"] = sorted(deny)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    ensure_openclaw_workspace(state_dir)


def ensure_openclaw_workspace(state_dir: Path) -> None:
    workspace = state_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENTS.md").write_text(
        "# PTA Benchmark Baseline\n\nFollow the current benchmark task. Do not run onboarding or bootstrap workflows.\n",
        encoding="utf-8",
    )
    for filename in ("SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md"):
        path = workspace / filename
        if not path.exists():
            path.write_text("", encoding="utf-8")
    bootstrap = workspace / "BOOTSTRAP.md"
    if bootstrap.exists():
        bootstrap.unlink()


def openclaw_environment(repo_root: Path) -> dict[str, str]:
    load_dotenv()
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = str(openclaw_state_dir(repo_root))
    env["OPENCLAW_CONFIG_PATH"] = str(openclaw_config_path(repo_root))
    env.setdefault("NO_COLOR", "1")
    return env


def current_openclaw_model_id() -> str:
    AnthropicProvider.load_environment()
    model_id = AnthropicProvider.model_id_from_env()
    if not model_id:
        raise RuntimeError("ANTHROPIC_MODEL is required for OpenClaw baseline runs.")
    return model_id


def extract_final_json(stdout: str) -> dict[str, Any]:
    parsed = parse_json_if_possible(stdout)
    if parsed is not None:
        found = find_success_object(parsed)
        if found is not None:
            return found
        for text in iter_strings(parsed):
            found = find_success_object(parse_json_if_possible(text))
            if found is not None:
                return found
            for candidate in extract_json_objects(text):
                found = find_success_object(parse_json_if_possible(candidate))
                if found is not None:
                    return found

    for candidate in extract_json_objects(stdout):
        found = find_success_object(parse_json_if_possible(candidate))
        if found is not None:
            return found

    raise ValueError("Could not find a final JSON object containing a success field in OpenClaw output.")


def parse_json_if_possible(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def find_success_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if "success" in value and isinstance(value["success"], bool):
            return value
        for child in value.values():
            found = find_success_object(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_success_object(child)
            if found is not None:
                return found
    return None


def iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_strings(child)


def extract_json_objects(text: str) -> list[str]:
    objects = []
    start = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
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
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:index + 1])
                    start = None
    return objects


def infer_llm_call_count(stdout: str) -> int:
    parsed = parse_json_if_possible(stdout)
    for key in ("llm_call_count", "model_call_count", "modelCalls", "model_calls"):
        value = find_numeric_key(parsed, key)
        if value is not None:
            return int(value)
    return 0


def extract_openclaw_session_metrics(repo_root: Path, openclaw_session_id: str, stdout: str = "") -> dict[str, Any]:
    session_file = openclaw_state_dir(repo_root) / "agents" / "main" / "sessions" / f"{openclaw_session_id}.jsonl"
    if not session_file.exists():
        return {
            "session_file": str(session_file),
            "model_call_count": infer_llm_call_count(stdout),
            "tool_call_count": infer_tool_call_count(stdout),
            "source": "stdout_fallback",
        }
    events = []
    with session_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    metrics = extract_openclaw_metrics_from_events(events)
    metrics["session_file"] = str(session_file)
    metrics["source"] = "openclaw_session_jsonl"
    return metrics


def extract_openclaw_metrics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    assistant_messages = [
        event.get("message", {})
        for event in events
        if event.get("type") == "message" and event.get("message", {}).get("role") == "assistant"
    ]
    tool_result_messages = [
        event.get("message", {})
        for event in events
        if event.get("type") == "message" and event.get("message", {}).get("role") == "toolResult"
    ]
    tool_calls = []
    for message in assistant_messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and block.get("type") == "toolCall":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "arguments": block.get("arguments") or {},
                    }
                )

    usage_sum: dict[str, int | float] = {}
    cost_sum: dict[str, int | float] = {}
    model_call_count = 0
    for message in assistant_messages:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        model_call_count += 1
        for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
            value = usage.get(key)
            if isinstance(value, int | float):
                usage_sum[key] = usage_sum.get(key, 0) + value
        cost = usage.get("cost")
        if isinstance(cost, dict):
            for key in ("input", "output", "cacheRead", "cacheWrite", "total"):
                value = cost.get(key)
                if isinstance(value, int | float):
                    cost_sum[key] = cost_sum.get(key, 0) + value

    return {
        "model_call_count": model_call_count,
        "assistant_message_count": len(assistant_messages),
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_result_messages),
        "tool_error_count": sum(1 for message in tool_result_messages if message.get("isError")),
        "resource_read_count": sum(1 for call in tool_calls if call.get("name") == "pta-benchmark__read_benchmark_resource"),
        "non_resource_tool_call_count": sum(1 for call in tool_calls if call.get("name") != "pta-benchmark__read_benchmark_resource"),
        "tool_sequence": tool_calls,
        "usage_sum": usage_sum,
        "cost_sum": cost_sum,
    }


def infer_tool_call_count(stdout: str) -> int:
    parsed = parse_json_if_possible(stdout)
    tool_summary_calls = find_path(parsed, ["meta", "toolSummary", "calls"])
    if isinstance(tool_summary_calls, int | float):
        return int(tool_summary_calls)
    for key in ("tool_call_count", "toolCalls", "tool_calls"):
        value = find_numeric_key(parsed, key)
        if value is not None:
            return int(value)
    return 0


def find_path(value: Any, path: list[str]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def find_numeric_key(value: Any, key: str) -> int | float | None:
    if isinstance(value, dict):
        if key in value and isinstance(value[key], int | float):
            return value[key]
        for child in value.values():
            found = find_numeric_key(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_numeric_key(child, key)
            if found is not None:
                return found
    return None


def openclaw_package_dir(repo_root: Path) -> Path:
    return repo_root / "baselines" / "openclaw"


def openclaw_state_dir(repo_root: Path) -> Path:
    return openclaw_package_dir(repo_root) / "state"


def openclaw_config_path(repo_root: Path) -> Path:
    return openclaw_state_dir(repo_root) / "openclaw.json"


def openclaw_local_binary_exists(repo_root: Path) -> bool:
    bin_name = "openclaw.cmd" if sys.platform.startswith("win") else "openclaw"
    return (openclaw_package_dir(repo_root) / "node_modules" / ".bin" / bin_name).exists()


def npm_executable() -> str:
    return "npm.cmd" if sys.platform.startswith("win") else "npm"


def compact_openclaw_model_label(model_id: str) -> str:
    lowered = model_id.lower()
    if "haiku" in lowered:
        return "haiku"
    if "sonnet" in lowered:
        return "sonnet"
    if "opus" in lowered:
        return "opus"
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in lowered)


def openclaw_model_arg(model_id: str) -> str:
    if "/" in model_id:
        return model_id
    if model_id.lower().startswith("claude"):
        return f"anthropic/{model_id}"
    return model_id


def session_label(label: str, model_label: str | None) -> str:
    return f"{model_label}-{label}" if model_label else label


def redact_command(command: list[str]) -> list[str]:
    return scrub_secrets(command)
