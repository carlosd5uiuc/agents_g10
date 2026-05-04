from typing import Any, Dict, List
import json
import argparse
from datetime import datetime, timedelta

from typing import Any, Dict

from typing import Any, Dict


def grade_task_06(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 3
    PA = 0
    TSR = 0

    #  "preferences": [
    #         "User would like to pay less than 100."
    #     ],
    #     "hard_constraints": [
    #         "Identify all pending bills",
    #         "Create a payment plan",
    #         "Alert if total pending bill amount exceeds budget 120."
    #     ],
    
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
        "CVC": CVC / 4,
        "PA": PA / 1
    }


def grade_task_05(task_data: Dict[str, Any]) -> Dict[str, Any]:
    CVC = 3
    PA = 0
    TSR = 0

    repair = task_data.get("repair_recommendation", {})

    diagnosis = str(task_data.get("diagnosis", "")).lower()
    likely_cause = str(task_data.get("likely_cause", "")).lower()

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

    appointment = task_data["appointment_confirmation"]

    is_dermatologist = appointment["specialty"].lower() == "dermatologist"
    supports_eczema = "eczema" in [item.lower() for item in appointment["supports"]]
    copay_valid = appointment["copay"] <= 50

    is_friday_after_3pm = (
        appointment["weekday"].lower() == "friday"
        and int(appointment["time"].split(":")[0]) > 15
    )

    if task_data["success"] and is_dermatologist and supports_eczema and copay_valid:
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
        task_data['catering_confirmation']['total'] < 150 and \
        task_data['catering_confirmation']['vegetarian'] < 120 and \
        len(task_data['invite_log']) == 3:
        TSR = 1

    if task_data['catering_confirmation']['total'] < 150: CVC -= 1
    if task_data['catering_confirmation']['vegetarian'] < 120: CVC -= 1
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

    CVC = 3
    PA = 0
    TSR = 0

    if task_data['success'] and \
        task_data['repair_confirmation']['in_network'] and \
        (task_data['repair_confirmation']['weekday'].lower() != 'thursday') and \
        int(task_data['repair_confirmation']['deductible']) < 120:
        TSR = 1

    if task_data['repair_confirmation']['in_network']: CVC -= 1
    if task_data['repair_confirmation']['weekday'].lower() != 'thursday': CVC -= 1
    if task_data['repair_confirmation']['deductible'] < 120: CVC -= 1

    if task_data['repair_confirmation']['current_week']: PA += 1

    return {
        "id": "task_02",
        "TSR": TSR,
        "CVC": CVC / 3,
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

    for key, value in data.items():
        if key == "task_01":
            results.append(grade_task_01(value))
        if key == "task_02":
            results.append(grade_task_02(value))
        if key == "task_03":
            results.append(grade_task_03(value))
        if key == "task_04":
            results.append(grade_task_04(value))
        if key == "task_05":
            results.append(grade_task_05(value))
        if key == "task_06":
            results.append(grade_task_06(value))
        

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

