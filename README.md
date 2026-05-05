# PTA Agent Benchmark

This repository contains:

- `agents/pta_agent`: custom policy-driven PTA agent
- `mcp-server`: deterministic MCP benchmark environment
- `grader.py`: TSR/CVC/PA grader
- `tasks_description.json`: task prompts, constraints, preferences, and output schemas
- `tool_schema.json`: tool schemas exposed to the agent

## Setup

Create `.env` in the repo root:

```text
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-4-5
```

Install/sync dependencies:

```powershell
uv sync
```

## Commands

Run all 10 tasks with Anthropic, wait 10 seconds between tasks, and run the grader automatically:

```powershell
uv run pta run-all
```

Run one task with Anthropic:

```powershell
uv run pta run-task task_04
```

Run tests:

```powershell
uv run pta test
```

Set up the project-local OpenClaw baseline:

```powershell
uv run pta setup-openclaw
```

Run all 10 tasks with stock OpenClaw and grade the results:

```powershell
uv run pta run-openclaw-all
```

Run one task with stock OpenClaw:

```powershell
uv run pta run-openclaw-task task_04
```

## Outputs

Runs are written to:

```text
outputs\sessions\<session_id>\
```

For `run-all`, the session directory contains:

```text
session_summary.json
grader_bundle.json
grader_results.json
task_01\
  final.json
  summary.json
  state_snapshot.json
  trace.jsonl
...
task_10\
  final.json
  summary.json
  state_snapshot.json
  trace.jsonl
```

Use `grader_results.json` to view TSR/CVC/PA scores.
Use `session_summary.json` to view run-level metrics:

```text
total_llm_calls
repair_count
invalid_model_output_count
tool_call_count
verification_failure_count
average_steps_per_task
```

## Notes

- The PTA agent is outside `mcp-server`.
- The agent interacts with the benchmark only through MCP resource reads and tool calls.
- Claude proposes actions only; Python policy, execution, verification, and logging control the run.
- `run-all` uses Anthropic by default and automatically creates grader input/output files.
- The benchmark resources include distractor options and edge cases for agent comparison.
- The OpenClaw baseline is installed under `baselines/openclaw` and uses its own local state/config directory.
- `mcp-server` exposes `read_benchmark_resource(uri)` so OpenClaw can read benchmark resources through MCP tools.
- OpenClaw should use the same MCP server, produce the same `final.json` format, and be graded by the same `grader.py`.
