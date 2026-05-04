from __future__ import annotations

import unittest
from pathlib import Path

from agents.pta_agent.models import ActionProposal, PolicyOutcome
from agents.pta_agent.policy import PolicyEngine
from agents.pta_agent.state import StateManager
from agents.pta_agent.task_interpreter import TaskInterpreter
from agents.pta_agent.trace import scrub_secrets
from agents.pta_agent.verifier import Verifier


REPO_ROOT = Path(__file__).resolve().parents[3]


class PolicyAndVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = TaskInterpreter(REPO_ROOT)

    def test_rejects_malformed_action(self) -> None:
        with self.assertRaises(ValueError):
            ActionProposal.from_mapping({"action": "call_tool", "arguments": {}})

    def test_policy_blocks_invalid_ride(self) -> None:
        task = self.interpreter.load("task_01")
        state = StateManager(task)
        state.add_resource(
            "transportation://list",
            [{"id": "LY-BAD", "arrival_time": "2026-05-02T11:00:00", "cost": 99, "surge_pricing": True, "from": "Chicago", "to": "Urbana"}],
        )
        proposal = ActionProposal.from_mapping({"action": "call_tool", "tool_name": "create_travel_arrangement", "arguments": {"ride_id": "LY-BAD"}})
        decision = PolicyEngine().evaluate(proposal, task, state)
        self.assertNotEqual(decision.outcome.value, "allow")

    def test_task_04_clarification_is_repaired(self) -> None:
        task = self.interpreter.load("task_04")
        state = StateManager(task)
        proposal = ActionProposal.from_mapping({"action": "ask_clarification", "message": "What date is Friday?"})

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        self.assertIn("2026-05-08T16:00:00", decision.reasons[0])

    def test_task_06_final_rejects_settled_pending_bills(self) -> None:
        task = self.interpreter.load("task_06")
        state = StateManager(task)
        state.add_resource(
            "household-bills://list",
            [
                {"id": "bill_pending", "name": "Pending", "amount": 10, "due": "2026-05-03T00:00:00", "settled": False},
                {"id": "bill_settled", "name": "Settled", "amount": 10, "due": "2026-05-03T00:00:00", "settled": True},
            ],
        )
        state.add_tool_result(
            "schedule_payment",
            {"bill_id": "bill_pending", "payment_date": "2026-05-03", "amount": 10},
            {"payment_confirmation_id": "pay-1", "bill_id": "bill_pending", "payment_date": "2026-05-03", "amount": 10},
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "finalize",
                "final_output": {
                    "success": True,
                    "plan_summary": "Bad plan",
                    "pending_bills": [
                        {"bill_id": "bill_pending", "amount": 10, "settled": False},
                        {"bill_id": "bill_settled", "amount": 10, "settled": True},
                    ],
                    "scheduled_payments": [],
                    "alert": "",
                },
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)

    def test_task_07_requires_calendar_evidence_for_every_activity(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        activities = [
            {
                "activity_id": f"workout_{index}",
                "activity_type": "cardio" if index < 3 else "strength",
                "muscle_group": "cardio" if index < 3 else f"group_{index}",
                "day": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][index],
                "weekday": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][index],
                "start_time": f"2026-05-0{index + 4}T18:00:00",
                "end_time": f"2026-05-0{index + 4}T18:30:00",
            }
            for index in range(6)
        ]
        state.add_resource("workout-sessions://list", activities)
        for index, activity in enumerate(activities[:5]):
            state.add_tool_result(
                "create_calendar_entry",
                {"date": activity["start_time"], "category": "EXERCISE"},
                {"confirmation_id": f"cal-{index}", "entry_date": activity["start_time"], "category": "EXERCISE"},
            )
        output = {
            "success": True,
            "scheduled_cardio": [
                {key: value for key, value in activity.items() if key != "day"}
                for activity in activities[:3]
            ],
            "scheduled_strength": [
                {key: value for key, value in activity.items() if key != "day"}
                for activity in activities[3:]
            ],
            "workout_calendar_confirmation": [f"cal-{index}" for index in range(5)],
        }
        proposal = ActionProposal.from_mapping({"action": "finalize", "final_output": output})

        decision = PolicyEngine().evaluate(proposal, task, state)
        verification = Verifier().verify(task, state, output)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        self.assertFalse(verification.ok)

    def test_task_10_blocks_payment_below_minimum_balance(self) -> None:
        task = self.interpreter.load("task_10")
        state = StateManager(task)
        state.add_resource(
            "pending-bills://list",
            [{"id": "card", "amount": 250, "due": "2026-04-22T10:00:00"}],
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "schedule_payment",
                "arguments": {"bill_id": "card", "payment_date": "2026-04-22", "amount": 250},
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)

    def test_verifier_rejects_hallucinated_confirmation(self) -> None:
        task = self.interpreter.load("task_01")
        state = StateManager(task)
        state.add_resource(
            "transportation://list",
            [{
                "id": "LY-1004",
                "from": "Chicago",
                "to": "Urbana",
                "departure_time": "2026-05-02T05:45:00",
                "arrival_time": "2026-05-02T08:15:00",
                "cost": 35,
                "surge_pricing": False,
                "rideshare": True,
            }],
        )
        state.add_tool_result("create_travel_arrangement", {"ride_id": "LY-1004"}, {"confirmation_id": "real-id", "ride_id": "LY-1004"})
        state.add_tool_result("create_calendar_entry", {"date": "2026-05-02T08:15:00", "category": "RIDE"}, {"confirmation_id": "cal-id"})
        output = {
            "success": True,
            "travel_confirmation": {
                "confirmation_id": "fake-id",
                "id": "LY-1004",
                "from": "Chicago",
                "to": "Urbana",
                "departure_time": "2026-05-02T05:45:00",
                "arrival_time": "2026-05-02T08:15:00",
                "cost": 35,
                "surge_pricing": False,
                "rideshare": True,
            },
            "calendar": {"confirmation_id": "cal-id"},
        }
        result = Verifier().verify(task, state, output)
        self.assertFalse(result.ok)

    def test_scrubs_api_keys(self) -> None:
        scrubbed = scrub_secrets({"ANTHROPIC_API_KEY": "secret", "nested": {"token": "abc"}})
        self.assertEqual(scrubbed["ANTHROPIC_API_KEY"], "[REDACTED]")
        self.assertEqual(scrubbed["nested"]["token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
