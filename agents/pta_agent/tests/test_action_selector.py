from __future__ import annotations

import unittest
from typing import Any

from agents.pta_agent.action_selector import ActionSelector
from agents.pta_agent.models import TaskSpec
from agents.pta_agent.providers import ModelProvider, ProviderRateLimitError
from agents.pta_agent.state import StateManager


class RateLimitedProvider(ModelProvider):
    name = "rate-limited"
    model_id = "test"

    async def propose(self, task: TaskSpec, state: StateManager, repair_context: str | None = None) -> dict[str, Any]:
        raise ProviderRateLimitError("rate limited", retry_after_seconds=12.5)


class ActionSelectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_is_not_treated_as_malformed_json(self) -> None:
        task = TaskSpec(
            task_id="task_01",
            prompt="",
            hard_constraints=[],
            preferences=[],
            output_structure={"success": "bool"},
            resource_uris=[],
            tool_names=[],
            tool_schemas=[],
            irreversible_tools=set(),
        )
        selection = await ActionSelector(RateLimitedProvider()).next_action(task, StateManager(task))

        self.assertTrue(selection.rate_limited)
        self.assertEqual(selection.retry_after_seconds, 12.5)
        self.assertIn("rate limited", selection.error or "")


if __name__ == "__main__":
    unittest.main()
