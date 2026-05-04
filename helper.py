from collections import defaultdict
from typing import Any, Dict, List
from datetime import datetime, time, timedelta

TASK_10_GIVEN_DATE = datetime.fromisoformat("2026-04-22T12:00:00")
TASK_10_LOOKBACK = timedelta(days=3)


def avoids_day_time_block(
        activity: Dict[str, Any],
        blocked_day: str,
        blocked_start: time,
        blocked_end: time
    ) -> bool:
        """
        Returns True if the activity does NOT overlap the blocked day/time window.
        """

        activity_day = activity.get("day") or activity.get("weekday")
        if activity_day != blocked_day:
            return True

        activity_start = datetime.fromisoformat(activity["start_time"]).time()
        activity_end = datetime.fromisoformat(activity["end_time"]).time()

        overlaps_block = activity_start < blocked_end and activity_end > blocked_start

        return not overlaps_block


def get_all_scheduled_activities(task_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return task_data.get("scheduled_cardio", []) + task_data.get("scheduled_strength", [])


def has_strength_cardio_pair(task_data: Dict[str, Any]) -> bool:
    """
    True if at least one weekday has both a strength activity and a cardio activity.
    """
    activities = get_all_scheduled_activities(task_data)

    types_by_day = defaultdict(set)

    for activity in activities:
        weekday = activity.get("weekday")
        activity_type = activity.get("activity_type")

        if weekday and activity_type:
            types_by_day[weekday].add(activity_type)

    return any(
        "strength" in activity_types and "cardio" in activity_types
        for activity_types in types_by_day.values()
    )


def no_more_than_one_activity_type_per_day(task_data: Dict[str, Any]) -> bool:
    """
    True if no day has more than one cardio or more than one strength activity.
    """
    activities = get_all_scheduled_activities(task_data)

    counts_by_day_and_type = defaultdict(int)

    for activity in activities:
        weekday = activity.get("weekday")
        activity_type = activity.get("activity_type")

        if weekday and activity_type:
            counts_by_day_and_type[(weekday, activity_type)] += 1

    return all(count <= 1 for count in counts_by_day_and_type.values())


def all_due_bills_scheduled(task_data: Dict[str, Any]) -> bool:
    due_bill_ids = {payment["id"] for payment in task_10_due_window_bills(task_data)}
    return due_bill_ids == scheduled_bill_ids(task_data)


def partial_due_schedule_with_alert(task_data: Dict[str, Any]) -> bool:
    due_bill_ids = {payment["id"] for payment in task_10_due_window_bills(task_data)}
    scheduled_ids = scheduled_bill_ids(task_data)
    omitted_due_ids = due_bill_ids - scheduled_ids

    return (
        bool(omitted_due_ids)
        and bool(scheduled_ids)
        and scheduled_ids.issubset(due_bill_ids)
        and projected_balance_never_below_200(task_data)
        and overdraft_alert_correct(task_data)
    )


def task_10_due_window_bills(task_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    start_date = TASK_10_GIVEN_DATE - TASK_10_LOOKBACK
    due_bills = []

    for payment in task_data.get("payments", []):
        try:
            due_date = datetime.fromisoformat(str(payment.get("due_date") or payment.get("due")))
        except Exception:
            continue

        if start_date <= due_date <= TASK_10_GIVEN_DATE:
            due_bills.append(payment)

    return due_bills


def scheduled_bill_ids(task_data: Dict[str, Any]) -> set[str]:
    return {
        payment.get("bill_id")
        for payment in task_data.get("scheduled_payments", [])
        if payment.get("bill_id")
    }

def projected_balance_never_below_200(task_data: dict) -> bool:
    starting_balance = 300
    minimum_balance = 200

    payments = task_data.get("payments", [])
    scheduled_payments = task_data.get("scheduled_payments", [])

    payment_amounts = {
        payment.get("id"): payment.get("amount", 0)
        for payment in payments
    }

    total_scheduled_amount = 0

    for scheduled_payment in scheduled_payments:
        bill_id = scheduled_payment.get("bill_id")
        amount = payment_amounts.get(bill_id, 0)

        if isinstance(amount, (int, float)):
            total_scheduled_amount += amount

    projected_balance = starting_balance - total_scheduled_amount

    return projected_balance >= minimum_balance

def overdraft_alert_correct(task_data: dict) -> bool:
    balance_ok = projected_balance_never_below_200(task_data)
    overdraft_alert = task_data.get("overdraft_alert")
    due_bill_ids = {payment["id"] for payment in task_10_due_window_bills(task_data)}
    omitted_due_ids = due_bill_ids - scheduled_bill_ids(task_data)

    if omitted_due_ids:
        if not isinstance(overdraft_alert, str) or not overdraft_alert.strip():
            return False
        lowered_alert = overdraft_alert.lower()
        return (
            any(str(bill_id).lower() in lowered_alert for bill_id in omitted_due_ids)
            or "balance" in lowered_alert
            or "overdraft" in lowered_alert
            or "cannot" in lowered_alert
        )

    if balance_ok:
        return overdraft_alert is None or isinstance(overdraft_alert, str)

    return isinstance(overdraft_alert, str) and overdraft_alert.strip() != ""
