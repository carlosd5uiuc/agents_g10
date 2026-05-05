from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.pta_agent.security_benchmark import (
    build_openclaw_security_message,
    build_security_scenarios,
    build_security_task,
    sensitive_openclaw_tool_calls,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class SecurityBenchmarkTests(unittest.TestCase):
    def test_security_benchmark_has_five_scenarios(self) -> None:
        scenarios = build_security_scenarios()

        self.assertEqual(len(scenarios), 5)
        self.assertEqual(
            {scenario.scenario_id for scenario in scenarios},
            {
                "direct_private_tool_injection",
                "direct_household_context_injection",
                "indirect_resource_injection",
                "indirect_appointment_intake_injection",
                "indirect_return_authorization_injection",
            },
        )

    def test_security_task_adds_indirect_injection_resource(self) -> None:
        scenario = next(item for item in build_security_scenarios() if item.scenario_id == "indirect_resource_injection")

        task = build_security_task(REPO_ROOT, scenario)

        self.assertIn("vendor://travel_brief", task.resource_uris)
        self.assertIn("transportation://list", task.resource_uris)
        self.assertNotIn("get_user_profile", task.tool_names)

    def test_security_task_adds_new_indirect_resources(self) -> None:
        scenarios = build_security_scenarios()
        appointment = next(item for item in scenarios if item.scenario_id == "indirect_appointment_intake_injection")
        return_auth = next(item for item in scenarios if item.scenario_id == "indirect_return_authorization_injection")

        appointment_task = build_security_task(REPO_ROOT, appointment)
        return_task = build_security_task(REPO_ROOT, return_auth)

        self.assertIn("security://appointment_intake_brief", appointment_task.resource_uris)
        self.assertIn("security://return_authorization_brief", return_task.resource_uris)
        self.assertNotIn("get_calendar_events", appointment_task.tool_names)
        self.assertNotIn("read_private_user_profile", return_task.tool_names)

    def test_openclaw_security_message_is_chat_style(self) -> None:
        scenario = build_security_scenarios()[0]
        task = build_security_task(REPO_ROOT, scenario)

        message = build_openclaw_security_message(task, scenario)

        self.assertIn("stock_chat_agent_security_eval", message)
        self.assertIn("get_user_profile", message)
        self.assertNotIn("Use only the configured pta-benchmark MCP environment", message)
        self.assertNotIn("prompt_injection", message)
        self.assertNotIn("output_structure", message)

    def test_sensitive_openclaw_tool_call_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "openclaw_metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "tool_sequence": [
                            {"name": "pta-benchmark__read_benchmark_resource", "arguments": {}},
                            {"name": "pta-benchmark__get_user_profile", "arguments": {}},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            calls = sensitive_openclaw_tool_calls(metrics_path)

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["matched_sensitive_tool"], "get_user_profile")


if __name__ == "__main__":
    unittest.main()
