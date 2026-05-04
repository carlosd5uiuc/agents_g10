import json
import argparse

from datetime import datetime, timedelta, time
from typing import Any, Dict, List

from helper import avoids_day_time_block, has_strength_cardio_pair, no_more_than_one_activity_type_per_day, all_due_bills_scheduled, partial_due_schedule_with_alert, projected_balance_never_below_200, overdraft_alert_correct

def grade_task_10(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 2
    PA = 0
    TSR = 0

    scheduled_condition_met = all_due_bills_scheduled(task_data)
    balance_condition_met = projected_balance_never_below_200(task_data)
    alert_condition_met = overdraft_alert_correct(task_data)

    # Scenario 1: normal success
    all_scheduled_safely = (
        scheduled_condition_met and
        balance_condition_met
    )

    # Scenario 2: cannot schedule all safely, but alert is emitted
    partial_schedule_with_alert = partial_due_schedule_with_alert(task_data)

    if task_data.get("success") and (all_scheduled_safely or partial_schedule_with_alert):
        TSR = 1

    if scheduled_condition_met or partial_schedule_with_alert:
        CVC -= 1

    if balance_condition_met or alert_condition_met:
        CVC -= 1

    if alert_condition_met:
        PA += 1

    return {
        "id": "task_10",
        "TSR": TSR,
        "CVC": CVC / 2,
        "PA": PA / 1
    }


def grade_task_09(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 4
    PA = 0
    TSR = 0

    return_is_free = task_data['return']['free_return']
    delivery_method_dropoff = task_data['return']['delivery_method'] == 'drop-off'
    refund_original_payment = task_data['return']['refund_method'] == 'original_payment'
    return_calendar_entry_exists = task_data['calendar_entry']['confirmation_id'] is not None and task_data['calendar_entry']['confirmation_id'] != ""

    if task_data["success"] and return_is_free and \
        delivery_method_dropoff and refund_original_payment and \
        return_calendar_entry_exists:
        TSR = 1

    if return_is_free:
        CVC -= 1

    if delivery_method_dropoff:
        CVC -= 1

    if refund_original_payment:
        CVC -= 1

    if return_calendar_entry_exists:
        CVC -= 1

    # PA
    return_before_15th = False

    try:
        deadline = datetime.strptime(
            task_data["calendar_entry"]["deadline"],
            "%Y-%m-%d"
        )

        return_before_15th = deadline.day < 15

    except Exception:
        return_before_15th = False
    
    if return_before_15th:
        PA += 1

    return {
        "id": "task_09",
        "TSR": TSR,
        "CVC": CVC / 4,
        "PA": PA / 1
    }

def grade_task_08(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 3
    PA = 0
    TSR = 0

    generated_report = task_data.get("generated_report", {})
    suggestions = generated_report.get("suggestions", []) if isinstance(generated_report, dict) else []
    try:
        total_reduction = int(generated_report.get("total_reduction", 0))
    except (TypeError, ValueError):
        total_reduction = 0

    reduction_target_met = total_reduction >= 150
    min_suggestions = isinstance(suggestions, list) and len(suggestions) >= 1
    cuts_only_from_non_priority = (
        isinstance(suggestions, list) and
        all(not s.get('priority_category') for s in suggestions if isinstance(s, dict))
    )

    if task_data["success"] and reduction_target_met and \
    min_suggestions and cuts_only_from_non_priority:
        TSR = 1

    if reduction_target_met: CVC -= 1
    if min_suggestions: CVC -= 1
    if cuts_only_from_non_priority: CVC -= 1

    cut_categories = {
        suggestion.get("category")
        for suggestion in suggestions
        if isinstance(suggestion, dict)
    }
    if "health" not in cut_categories:
        PA += 1 

    if "gym" not in cut_categories:
        PA += 1

    return {
        "id": "task_08",
        "TSR": TSR,
        "CVC": CVC / 3,
        "PA": PA / 2
    }

def grade_task_07(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 7
    PA = 0
    TSR = 0
    
    scheduled_cardio = task_data.get("scheduled_cardio", [])
    scheduled_strength = task_data.get("scheduled_strength", [])
    all_scheduled_activities = scheduled_cardio + scheduled_strength
    monday_constraint_met = all([
        avoids_day_time_block(activity=t, blocked_day="Monday", blocked_start=time(8, 0), blocked_end=time(17,0)) for t in all_scheduled_activities
    ])
    wednesday_constraint_met = all([
        avoids_day_time_block(activity=t, blocked_day="Wednesday", blocked_start=time(8, 0), blocked_end=time(17,0)) for t in all_scheduled_activities
    ])
    sufficient_strength_routines = len(scheduled_strength) >= 3
    sufficient_cardio_routines = len(scheduled_cardio) >= 3
    paired_strength_cardio = has_strength_cardio_pair(task_data)
    valid_type_limit = no_more_than_one_activity_type_per_day(task_data)
    confirmations = task_data.get("workout_calendar_confirmation", [])
    calendar_entries_exist = (
        isinstance(confirmations, list) and
        len(confirmations) == len(all_scheduled_activities) and
        all(isinstance(confirmation, str) and confirmation.strip() for confirmation in confirmations)
    )

    if task_data['success'] and \
        monday_constraint_met and wednesday_constraint_met and \
        sufficient_strength_routines and sufficient_cardio_routines and \
        paired_strength_cardio and valid_type_limit and \
        calendar_entries_exist:
        TSR = 1

    if monday_constraint_met:
        CVC -= 1

    if wednesday_constraint_met:
        CVC -= 1

    if sufficient_strength_routines:
        CVC -= 1

    if sufficient_cardio_routines:
        CVC -= 1

    if paired_strength_cardio:
        CVC -= 1

    if valid_type_limit:
        CVC -= 1     

    if calendar_entries_exist:
        CVC -= 1

    # PA
    strength_muscle_groups = [
        activity.get("muscle_group")
        for activity in scheduled_strength
        if activity.get("muscle_group")
    ]

    distinct_strength_muscle_groups = (
        len(strength_muscle_groups) == len(set(strength_muscle_groups))
    )

    includes_swimming = any(
        "swim" in activity.get("activity_id", "").lower()
        or "swim" in activity.get("muscle_group", "").lower()
        for activity in scheduled_cardio
    )  

    if distinct_strength_muscle_groups: PA += 1
    if includes_swimming: PA += 1
    

    return {
        "id": "task_07",
        "TSR": TSR,
        "CVC": CVC / 7,
        "PA": PA / 2
    }

def grade_task_06(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 3
    PA = 0
    TSR = 0
    total = sum([int(t['amount']) for t in task_data['pending_bills']])
    if total <= 100: PA +=1

    bill_are_pending = all([not t['settled'] for t in task_data['pending_bills']])
    payment_plan_exists = task_data['plan_summary'] is not None and task_data['plan_summary'] != ""
    alert = task_data.get("alert")
    alert_correct = (
        # If over budget, alert must exist and not be empty
        (total > 120 and isinstance(alert, str) and alert.strip() != "")
        or
        # If within budget, alert can be None or any string
        (total <= 120 and (alert is None or isinstance(alert, str)))
    )
    if bill_are_pending and payment_plan_exists and alert_correct: TSR = 1

    if bill_are_pending: CVC -= 1
    if payment_plan_exists: CVC -= 1
    if alert_correct: CVC -= 1

    return {
        "id": "task_06",
        "TSR": TSR,
        "CVC": CVC / 3,
        "PA": PA / 1
    }


def grade_task_05(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 3
    PA = 0
    TSR = 0

    repair = task_data.get("repair_recommendation", {})

    diagnosis = str(task_data.get("diagnosis", "")).lower()
    likely_cause = str(task_data.get("likely_cause", "")).lower()

    recommended_steps = task_data.get("recommended_steps")
    if recommended_steps is None:
        recommended_steps = repair.get("recommended_steps", [])
    estimated_cost = repair.get("estimated_cost")
    distance_miles = repair.get("distance_miles")

    diagnosed_drain_pump = (
        "drain pump" in diagnosis or
        "drain pump" in likely_cause
    )

    has_clear_steps = (
        isinstance(recommended_steps, list) and
        len(recommended_steps) > 0 and
        all(isinstance(step, str) and step.strip() for step in recommended_steps)
    )

    cost_under_200 = (
        isinstance(estimated_cost, (int, float)) and
        estimated_cost <= 200
    )

    within_5_miles = (
        isinstance(distance_miles, (int, float)) and
        distance_miles <= 5
    )

    if diagnosed_drain_pump:
        CVC -= 1

    if has_clear_steps:
        CVC -= 1

    if cost_under_200:
        CVC -= 1

    if within_5_miles:
        PA += 1

    if (
        task_data.get("success") is True and
        diagnosed_drain_pump and
        has_clear_steps and
        cost_under_200
    ):
        TSR = 1

    return {
        "id": "task_05",
        "TSR": TSR,
        "CVC": CVC / 3,
        "PA": PA / 1
    }

def grade_task_04(task_data: dict) -> dict:
    CVC = 3
    PA = 0
    TSR = 0

    appointment = task_data.get("appointment_confirmation", {})

    is_dermatologist = str(appointment.get("specialty", "")).lower() == "dermatologist"
    supports = appointment.get("supports", [])
    supports_eczema = isinstance(supports, list) and "eczema" in [str(item).lower() for item in supports]
    copay = appointment.get("copay")
    copay_valid = isinstance(copay, (int, float)) and copay <= 50

    try:
        appointment_hour = int(str(appointment.get("time", "")).split(":")[0])
    except (TypeError, ValueError):
        appointment_hour = -1

    is_friday_after_3pm = (
        str(appointment.get("weekday", "")).lower() == "friday"
        and appointment_hour > 15
    )

    if task_data.get("success") and is_dermatologist and supports_eczema and copay_valid:
        TSR = 1

    if is_dermatologist:
        CVC -= 1

    if supports_eczema:
        CVC -= 1

    if copay_valid:
        CVC -= 1

    if is_friday_after_3pm:
        PA += 1

    return {
        "id": "task_04",
        "TSR": TSR,
        "CVC": CVC / 3,
        "PA": PA / 1
    }

def grade_task_03(task_data: dict) -> dict:
    CVC = 3
    PA = 0
    TSR = 0

    if task_data['success'] and \
        task_data['catering_confirmation']['total'] <= 150 and \
        task_data['catering_confirmation']['vegetarian'] and \
        len(task_data['invite_log']) == 3:
        TSR = 1

    if task_data['catering_confirmation']['total'] <= 150: CVC -= 1
    if task_data['catering_confirmation']['vegetarian']: CVC -= 1
    if len(task_data['invite_log']) == 3: CVC -= 1

    if not task_data['catering_confirmation']['contains_nuts']: PA += 1

    return {
        "id": "task_03",
        "TSR": TSR,
        "CVC": CVC / 3,
        "PA": PA / 1
    }

def grade_task_02(task_data: dict) -> dict:
    """
    Grade Task 2: repair appointment scheduling.

    Metrics:
    - TSR: Task Success Rate, 1 if task succeeds, else 0
    - CVC: Constraint Violation Count, lower is better
    - PA: Preference Adherence, 1 if preferences are satisfied, else 0
    """

    CVC = 4
    PA = 0
    TSR = 0

    if task_data['success'] and \
        ('laptop' in task_data['repair_confirmation']['type_of_repair'].lower()) and \
        ('battery' in task_data['repair_confirmation']['type_of_repair'].lower()) and \
        task_data['repair_confirmation']['in_network'] and \
        (task_data['repair_confirmation']['weekday'].lower() != 'thursday') and \
        int(task_data['repair_confirmation']['deductible']) <= 120:
        TSR = 1

    if ('laptop' in task_data['repair_confirmation']['type_of_repair'].lower()) and \
        ('battery' in task_data['repair_confirmation']['type_of_repair'].lower()): CVC -= 1
    if task_data['repair_confirmation']['in_network']: CVC -= 1
    if task_data['repair_confirmation']['weekday'].lower() != 'thursday': CVC -= 1
    if task_data['repair_confirmation']['deductible'] <= 120: CVC -= 1

    if task_data['repair_confirmation']['current_week']: PA += 1

    return {
        "id": "task_02",
        "TSR": TSR,
        "CVC": CVC / 4,
        "PA": PA / 1
    }

def grade_task_01(task_data: Dict[str, Any]) -> Dict[str, Any]:
    scheduled_time = "2026-05-02T12:00:00"
    scheduled_dt = datetime.fromisoformat(scheduled_time)
    arrival_dt = datetime.fromisoformat(
    task_data["travel_confirmation"]["arrival_time"]
    )
    travel_information = task_data["travel_confirmation"]
    arrives_at_least_2_hours_before = arrival_dt <= scheduled_dt - timedelta(hours=2)
    arrives_at_least_3_hours_before = arrival_dt <= scheduled_dt - timedelta(hours=3)

    TSR = 0
    CVC = 4
    PA = 0

    if task_data['success'] and \
        arrives_at_least_2_hours_before and \
        travel_information['cost'] <= 45 and \
        not travel_information['surge_pricing'] and \
        travel_information['from'].lower() == 'chicago' and \
        travel_information['to'].lower() == 'urbana':
        TSR = 1

    if arrives_at_least_2_hours_before: CVC -= 1
    if travel_information['cost'] <= 45: CVC -= 1
    if not travel_information['surge_pricing']: CVC -= 1
    if (travel_information['from'].lower() == 'chicago' and \
        travel_information['to'].lower() == 'urbana'): CVC -= 1
    
    if travel_information['rideshare']: PA += 1
    if arrives_at_least_3_hours_before: PA += 1

    return {
        "id": "task_01",
        "TSR": TSR,
        "CVC": CVC / 4,
        "PA": PA / 2
    }

def grade_result(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    graders = {
        "task_01": grade_task_01,
        "task_02": grade_task_02,
        "task_03": grade_task_03,
        "task_04": grade_task_04,
        "task_05": grade_task_05,
        "task_06": grade_task_06,
        "task_07": grade_task_07,
        "task_08": grade_task_08,
        "task_09": grade_task_09,
        "task_10": grade_task_10,
    }

    for key, value in data.items():
        grader = graders.get(key)
        if grader is None:
            continue
        try:
            results.append(grader(value))
        except Exception as exc:
            results.append({"id": key, "TSR": 0, "CVC": 1, "PA": 0, "error": repr(exc)})
        

    return results

def main() -> None:
    parser = argparse.ArgumentParser(description="Grade an agent result from a JSON file.")
    parser.add_argument("json_file", help="Path to the JSON file to grade")

    args = parser.parse_args()

    with open(args.json_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    grade = grade_result(data)

    print(json.dumps(grade, indent=2))


if __name__ == "__main__":
    main()

