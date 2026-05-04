import argparse
import json
from typing import Any, Dict


def build_llm_prompt(task: Dict[str, Any]) -> str:
    preferences = "\n".join(
        f"- {preference}" for preference in task.get("preferences", [])
    )

    hard_constraints = "\n".join(
        f"- {constraint}" for constraint in task.get("hard_constraints", [])
    )

    output_structure = json.dumps(
        task.get("output_structure", {}),
        indent=2
    )

    return f"""
You are a Personal Task agent.

Task:
{task["prompt"]}

Hard constraints:
{hard_constraints}

User preferences:
{preferences}

You must return your final answer using exactly this JSON structure:
{output_structure}

Rules:
- Satisfy all hard constraints.
- Follow user preferences when possible.
- Return only valid JSON.
- Do not include markdown, explanations, or extra text.
""".strip()

def normalize_task_key(task_number: str) -> str:
    """
    Accepts:
    - 10
    - task_10
    - task_010 is not supported unless your JSON uses that key
    """
    if task_number.startswith("task_"):
        return task_number

    return f"task_{int(task_number):02d}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an LLM prompt from tasks_description.json"
    )
    parser.add_argument(
        "task_number",
        help="Task number or key. Example: 10 or task_10"
    )

    args = parser.parse_args()

    with open("tasks_description.json", "r", encoding="utf-8") as file:
        tasks_description = json.load(file)

    task_key = normalize_task_key(args.task_number)

    if task_key not in tasks_description:
        raise KeyError(f"Task not found: {task_key}")

    task = tasks_description[task_key]
    prompt = build_llm_prompt(task)

    print(prompt)


if __name__ == "__main__":
    main()
