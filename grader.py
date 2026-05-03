from typing import Any, Dict, List
import json
import argparse
from datetime import datetime, timedelta

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

