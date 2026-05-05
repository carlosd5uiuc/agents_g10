from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.pta_agent.models import ActionProposal, PolicyOutcome
from agents.pta_agent.policy import PolicyEngine, task_07_recommended_activities
from agents.pta_agent.runner import build_repair_context
from agents.pta_agent.state import StateManager
from agents.pta_agent.task_interpreter import TaskInterpreter
from agents.pta_agent.trace import scrub_secrets
from agents.pta_agent.verifier import Verifier


REPO_ROOT = Path(__file__).resolve().parents[3]


class PolicyAndVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = TaskInterpreter(REPO_ROOT)

    def real_task_07_sessions(self) -> list[dict]:
        return json.loads((REPO_ROOT / "mcp-server" / "resource_data" / "task_07.json").read_text())

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
        self.assertIn("derive the calendar datetime", decision.reasons[0])

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

    def test_task_06_repair_context_names_missing_and_invalid_bill_state(self) -> None:
        task = self.interpreter.load("task_06")
        state = StateManager(task)
        state.add_resource(
            "household-bills://list",
            [
                {"id": "bill_pending", "name": "Pending", "amount": 10, "due": "2026-05-03T00:00:00", "settled": False},
                {"id": "bill_other", "name": "Other", "amount": 12, "due": "2026-05-04T00:00:00", "settled": False},
                {"id": "bill_settled", "name": "Settled", "amount": 10, "due": "2026-05-03T00:00:00", "settled": True},
            ],
        )
        state.add_tool_result(
            "schedule_payment",
            {"bill_id": "bill_settled", "payment_date": "2026-05-03", "amount": 10},
            {"payment_confirmation_id": "pay-settled", "bill_id": "bill_settled", "payment_date": "2026-05-03", "amount": 10},
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "finalize",
                "final_output": {
                    "success": True,
                    "plan_summary": "Bad plan",
                    "pending_bills": [{"bill_id": "bill_pending", "amount": 10, "settled": False}],
                    "scheduled_payments": [],
                    "alert": "",
                },
            }
        )
        decision = PolicyEngine().evaluate(proposal, task, state)

        context = build_repair_context(task, state, proposal, decision.reasons)

        self.assertIn("Expected unsettled bill IDs: ['bill_other', 'bill_pending']", context)
        self.assertIn("Missing schedule_payment IDs: ['bill_other', 'bill_pending']", context)
        self.assertIn("Extra/invalid scheduled IDs: ['bill_settled']", context)
        self.assertIn("Do not schedule settled bills", context)

    def test_task_04_repair_context_tells_next_calendar_action(self) -> None:
        task = self.interpreter.load("task_04")
        state = StateManager(task)
        state.add_resource(
            "doctor://list",
            [
                {
                    "name": "Dr. Friday",
                    "specialty": "Dermatologist",
                    "supports": ["Eczema"],
                    "copay": 40,
                    "availability": ["Friday,16"],
                    "slot_datetimes": {"Friday,16": "2026-05-08T16:00:00"},
                }
            ],
        )
        state.add_tool_result(
            "set_up_doctor_appointment",
            {"doctor_name": "Dr. Friday", "appointment_time": "Friday,16"},
            {"confirmation_id": "appt-1", "doctor_name": "Dr. Friday", "appointment_time": "Friday,16"},
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "finalize",
                "final_output": {
                    "success": True,
                    "appointment_confirmation": {"confirmation_id": "appt-1", "name": "Dr. Friday"},
                    "calendar": {},
                },
            }
        )
        decision = PolicyEngine().evaluate(proposal, task, state)

        context = build_repair_context(task, state, proposal, decision.reasons)

        self.assertIn("date='2026-05-08T16:00:00'", context)
        self.assertIn("category='MEDICAL'", context)

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

    def test_task_07_calendar_policy_rejects_wrong_category_before_execution(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        state.add_resource(
            "workout-sessions://list",
            [{"activity_id": "run", "start_time": "2026-05-04T18:00:00"}],
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": "2026-05-04T18:00:00", "category": "CARDIO"},
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        self.assertIn("category EXERCISE", " ".join(decision.reasons))

    def test_task_07_recommended_selection_uses_six_valid_sessions_not_all_candidates(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        state.add_resource("workout-sessions://list", self.real_task_07_sessions())

        recommended = task_07_recommended_activities(state)
        recommended_ids = [activity["activity_id"] for activity in recommended]

        self.assertEqual(
            recommended_ids,
            [
                "strength_lower_01",
                "cardio_bike_01",
                "strength_push_01",
                "cardio_walk_01",
                "strength_upper_01",
                "cardio_swim_01",
            ],
        )
        self.assertNotIn("strength_upper_early", recommended_ids)
        self.assertNotIn("strength_core_blocked", recommended_ids)
        self.assertNotIn("cardio_swim_blocked", recommended_ids)

    def test_task_07_calendar_policy_allows_valid_non_recommended_observed_session(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        state.add_resource("workout-sessions://list", self.real_task_07_sessions())
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": "2026-05-04T17:30:00", "category": "EXERCISE"},
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    def test_task_07_calendar_policy_blocks_blocked_observed_session(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        state.add_resource("workout-sessions://list", self.real_task_07_sessions())
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "create_calendar_entry",
                "arguments": {"date": "2026-05-04T09:00:00", "category": "EXERCISE"},
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        self.assertIn("blocked Monday/Wednesday", " ".join(decision.reasons))

    def test_task_07_verifier_allows_non_recommended_valid_plan(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        sessions = self.real_task_07_sessions()
        state.add_resource("workout-sessions://list", sessions)
        by_id = {activity["activity_id"]: activity for activity in sessions}
        selected_ids = [
            "cardio_run_01",
            "cardio_bike_01",
            "cardio_swim_01",
            "strength_lower_01",
            "strength_core_01",
            "strength_upper_01",
        ]
        for index, activity_id in enumerate(selected_ids):
            activity = by_id[activity_id]
            state.add_tool_result(
                "create_calendar_entry",
                {"date": activity["start_time"], "category": "EXERCISE"},
                {"confirmation_id": f"cal-alt-{index}", "entry_date": activity["start_time"], "category": "EXERCISE"},
            )

        def output_activity(activity_id: str) -> dict:
            activity = by_id[activity_id]
            return {
                "activity_id": activity["activity_id"],
                "activity_type": activity["activity_type"],
                "muscle_group": activity["muscle_group"],
                "weekday": activity["day"],
                "start_time": activity["start_time"],
                "end_time": activity["end_time"],
            }

        output = {
            "success": True,
            "scheduled_cardio": [output_activity(activity_id) for activity_id in selected_ids[:3]],
            "scheduled_strength": [output_activity(activity_id) for activity_id in selected_ids[3:]],
            "workout_calendar_confirmation": [f"cal-alt-{index}" for index in range(6)],
        }
        proposal = ActionProposal.from_mapping({"action": "finalize", "final_output": output})

        decision = PolicyEngine().evaluate(proposal, task, state)
        verification = Verifier().verify(task, state, output)

        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)
        self.assertTrue(verification.ok, verification.errors)

    def test_task_08_policy_explains_expenses_are_cut_candidates_not_full_list(self) -> None:
        task = self.interpreter.load("task_08")
        state = StateManager(task)
        state.add_resource(
            "expenses://list",
            [
                {"category": "streaming", "amount": 45, "priority": False},
                {"category": "medicine", "amount": 70, "priority": True},
                {"category": "meal_delivery", "amount": 95, "priority": False},
            ],
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "generate_report",
                "arguments": {
                    "expenses": state.get_resource("expenses://list"),
                    "reduction_goal": "$150",
                    "suggestions": "Cut streaming and meal delivery.",
                },
            }
        )

        decision = PolicyEngine().evaluate(proposal, task, state)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        reason = " ".join(decision.reasons)
        self.assertIn("non-priority expense categories being considered for cuts", reason)
        self.assertIn("not the full expenses://list", reason)
        self.assertIn("Remove priority categories ['medicine']", reason)

    def test_task_08_repair_context_gives_valid_generate_report_shape(self) -> None:
        task = self.interpreter.load("task_08")
        state = StateManager(task)
        state.add_resource(
            "expenses://list",
            [
                {"category": "streaming", "amount": 45, "priority": False},
                {"category": "medicine", "amount": 70, "priority": True},
                {"category": "meal_delivery", "amount": 95, "priority": False},
                {"category": "books", "amount": 55, "priority": False},
            ],
        )
        proposal = ActionProposal.from_mapping(
            {
                "action": "call_tool",
                "tool_name": "generate_report",
                "arguments": {
                    "expenses": state.get_resource("expenses://list"),
                    "reduction_goal": "$150",
                    "suggestions": "Cut streaming and meal delivery.",
                },
            }
        )
        decision = PolicyEngine().evaluate(proposal, task, state)

        context = build_repair_context(task, state, proposal, decision.reasons)

        self.assertIn("do NOT pass the full expense list", context)
        self.assertIn("generate_report.arguments.expenses is the cut-candidate list", context)
        self.assertIn("Priority categories that must be excluded", context)
        self.assertIn("\"category\": \"streaming\"", context)
        self.assertIn("\"category\": \"meal_delivery\"", context)
        self.assertIn("\"category\": \"books\"", context)
        self.assertIn("Compacted in repair context", context)

    def test_task_07_repair_context_warns_against_more_irreversible_calendar_calls(self) -> None:
        task = self.interpreter.load("task_07")
        state = StateManager(task)
        state.add_resource("workout-sessions://list", self.real_task_07_sessions())
        activities = task_07_recommended_activities(state)
        for index, activity in enumerate(activities):
            state.add_tool_result(
                "create_calendar_entry",
                {"date": activity["start_time"], "category": "CARDIO"},
                {"confirmation_id": f"cal-{index}", "entry_date": activity["start_time"], "category": "CARDIO"},
            )
        output = {
            "success": True,
            "scheduled_cardio": activities[:3],
            "scheduled_strength": activities[3:],
            "workout_calendar_confirmation": [f"cal-{index}" for index in range(6)],
        }
        proposal = ActionProposal.from_mapping({"action": "finalize", "final_output": output})
        decision = PolicyEngine().evaluate(proposal, task, state)

        context = build_repair_context(task, state, proposal, decision.reasons)

        self.assertEqual(decision.outcome, PolicyOutcome.REPAIR)
        self.assertIn("Total create_calendar_entry tool calls so far: 6", context)
        self.assertIn("Recommended six-workout plan IDs", context)
        self.assertNotIn("Expected selected workout count", context)
        self.assertIn("Wrong-category calendar calls: 6", context)
        self.assertIn("Do NOT create additional create_calendar_entry calls.", context)
        self.assertIn("failed_constraints", context)

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
