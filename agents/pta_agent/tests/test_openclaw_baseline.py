from __future__ import annotations

import json
import unittest

from agents.pta_agent.models import TaskSpec
from agents.pta_agent.openclaw_baseline import (
    build_openclaw_message,
    extract_final_json,
    extract_openclaw_metrics_from_events,
    infer_tool_call_count,
    openclaw_model_arg,
)


class OpenClawBaselineTests(unittest.TestCase):
    def test_openclaw_prompt_uses_stock_agent_not_pta_action_schema(self) -> None:
        task = TaskSpec(
            task_id="task_01",
            prompt="Book a ride.",
            hard_constraints=["Arrive by 9."],
            preferences=[],
            output_structure={"success": "bool"},
            resource_uris=["transportation://list"],
            tool_names=["create_travel_arrangement"],
            tool_schemas=[{"name": "create_travel_arrangement", "input_schema": {"type": "object"}}],
            irreversible_tools={"create_travel_arrangement"},
        )

        payload = json.loads(build_openclaw_message(task))

        self.assertEqual(payload["role"], "stock_openclaw_baseline")
        self.assertIn("Do not use the PTA action proposal schema.", payload["benchmark_rules"])
        self.assertEqual(payload["task"]["resource_uris"], ["transportation://list"])

    def test_extract_final_json_from_openclaw_json_wrapper(self) -> None:
        stdout = json.dumps(
            {
                "response": "Done\n```json\n{\"success\": true, \"answer\": 7}\n```",
                "usage": {"modelCalls": 2},
            }
        )

        self.assertEqual(extract_final_json(stdout), {"success": True, "answer": 7})

    def test_claude_model_gets_anthropic_provider_prefix(self) -> None:
        self.assertEqual(
            openclaw_model_arg("claude-haiku-4-5-20251001"),
            "anthropic/claude-haiku-4-5-20251001",
        )
        self.assertEqual(openclaw_model_arg("anthropic/claude-sonnet-4-5"), "anthropic/claude-sonnet-4-5")

    def test_infers_openclaw_tool_summary_calls(self) -> None:
        stdout = json.dumps({"meta": {"toolSummary": {"calls": 3}}})

        self.assertEqual(infer_tool_call_count(stdout), 3)

    def test_extracts_exact_openclaw_session_metrics(self) -> None:
        events = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-1",
                            "name": "pta-benchmark__read_benchmark_resource",
                            "arguments": {"uri": "transportation://list"},
                        }
                    ],
                    "usage": {"input": 1, "output": 2, "cacheRead": 3, "cacheWrite": 4, "totalTokens": 10, "cost": {"total": 0.01}},
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "call-1",
                    "toolName": "pta-benchmark__read_benchmark_resource",
                    "isError": False,
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "{}"}],
                    "usage": {"input": 5, "output": 6, "totalTokens": 11, "cost": {"total": 0.02}},
                },
            },
        ]

        metrics = extract_openclaw_metrics_from_events(events)

        self.assertEqual(metrics["model_call_count"], 2)
        self.assertEqual(metrics["tool_call_count"], 1)
        self.assertEqual(metrics["tool_result_count"], 1)
        self.assertEqual(metrics["resource_read_count"], 1)
        self.assertEqual(metrics["usage_sum"]["totalTokens"], 21)
        self.assertEqual(metrics["cost_sum"]["total"], 0.03)


if __name__ == "__main__":
    unittest.main()
