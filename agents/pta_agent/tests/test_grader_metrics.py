from __future__ import annotations

import unittest

from grader import grade_task_04, grade_task_05, grade_task_06, grade_task_10


class GraderMetricTests(unittest.TestCase):
    def test_task_04_missing_confirmation_does_not_crash(self) -> None:
        grade = grade_task_04({"success": False, "message": "needs date"})

        self.assertEqual(grade["TSR"], 0)

    def test_task_05_uses_top_level_recommended_steps(self) -> None:
        grade = grade_task_05(
            {
                "success": True,
                "diagnosis": "Washer not draining",
                "likely_cause": "Drain pump blockage",
                "recommended_steps": ["Unplug washer.", "Clear drain pump filter."],
                "repair_recommendation": {
                    "service_name": "SpinCycle Pros",
                    "distance_miles": 5.0,
                    "estimated_cost": 90,
                },
            }
        )

        self.assertEqual(grade["TSR"], 1)
        self.assertEqual(grade["CVC"], 0)

    def test_task_06_cvc_is_normalized_by_three_constraints(self) -> None:
        grade = grade_task_06(
            {
                "success": True,
                "plan_summary": "Scheduled pending bills.",
                "pending_bills": [{"amount": 45, "settled": False}],
                "alert": "",
            }
        )

        self.assertEqual(grade["TSR"], 1)
        self.assertEqual(grade["CVC"], 0)

    def test_task_10_accepts_safe_partial_schedule_with_alert(self) -> None:
        grade = grade_task_10(
            {
                "success": True,
                "payments": [
                    {"id": "phone", "due_date": "2026-04-20T00:00:00", "amount": 40},
                    {"id": "internet", "due_date": "2026-04-21T00:00:00", "amount": 35},
                    {"id": "water", "due_date": "2026-04-22T09:00:00", "amount": 25},
                    {"id": "card", "due_date": "2026-04-22T10:00:00", "amount": 250},
                    {"id": "streaming", "due_date": "2026-04-24T00:00:00", "amount": 15},
                ],
                "scheduled_payments": [
                    {"confirmation_id": "a", "bill_id": "phone", "scheduled_date": "2026-04-20T00:00:00"},
                    {"confirmation_id": "b", "bill_id": "internet", "scheduled_date": "2026-04-21T00:00:00"},
                    {"confirmation_id": "c", "bill_id": "water", "scheduled_date": "2026-04-22T00:00:00"},
                ],
                "overdraft_alert": "Cannot schedule card because it would drop the balance below 200.",
            }
        )

        self.assertEqual(grade["TSR"], 1)
        self.assertEqual(grade["CVC"], 0)


if __name__ == "__main__":
    unittest.main()
