from collections import defaultdict
from typing import Any, Dict, List
from datetime import datetime, time


def avoids_day_time_block(
        activity: Dict[str, Any],
        blocked_day: str,
        blocked_start: time,
        blocked_end: time
    ) -> bool:
        """
        Returns True if the activity does NOT overlap the blocked day/time window.
        """

        if activity.get("day") != blocked_day:
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
