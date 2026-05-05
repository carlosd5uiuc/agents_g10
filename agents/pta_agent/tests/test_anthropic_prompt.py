from __future__ import annotations

import json
import unittest

from agents.pta_agent.models import TaskSpec
from agents.pta_agent.providers import (
    anthropic_text_block,
    build_initial_anthropic_prompt,
    build_turn_full_state_prompt,
)
from agents.pta_agent.state import StateManager


class AnthropicPromptTests(unittest.TestCase):
    def test_cache_control_block_is_available_for_stable_context(self) -> None:
        block = anthropic_text_block("stable prompt", cache=True)

        self.assertEqual(block["cache_control"], {"type": "ephemeral"})

    def test_initial_prompt_contains_schema_once(self) -> None:
        task = sample_task()

        prompt = json.loads(build_initial_anthropic_prompt(task))

        self.assertIn("tool_schemas", prompt["task"])
        self.assertIn("output_structure", prompt["task"])

    def test_turn_prompt_omits_repeated_schema_payloads(self) -> None:
        task = sample_task()
        state = StateManager(task)
        state.add_resource("demo://resource", {"id": "item-1"})

        prompt = json.loads(build_turn_full_state_prompt(task=task, state=state, repair_context=None))

        self.assertNotIn("allowed_tools", prompt)
        self.assertNotIn("tool_schemas", prompt)
        self.assertNotIn("output_structure", prompt)
        self.assertEqual(prompt["state"]["resources_read"], state.resources)

    def test_turn_prompt_uses_recent_failed_attempts_only(self) -> None:
        task = sample_task()
        state = StateManager(task)
        for index in range(5):
            state.add_failed_attempt({"index": index})

        prompt = json.loads(build_turn_full_state_prompt(task=task, state=state, repair_context="repair this"))

        self.assertEqual([item["index"] for item in prompt["state"]["failed_attempts"]], [2, 3, 4])
        self.assertEqual(prompt["state"]["summary"]["failed_attempt_count"], 5)


def sample_task() -> TaskSpec:
    return TaskSpec(
        task_id="task_demo",
        prompt="Do the demo task.",
        hard_constraints=["Use only demo resources."],
        preferences=[],
        output_structure={"success": "bool"},
        resource_uris=["demo://resource"],
        tool_names=["demo_tool"],
        tool_schemas=[
            {
                "name": "demo_tool",
                "input_schema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            }
        ],
        irreversible_tools=set(),
    )


if __name__ == "__main__":
    unittest.main()
