from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.pta_agent.cli import compact_model_label, grade_bundle, session_label
from agents.pta_agent.runner import write_grader_bundle, write_session_summary

REPO_ROOT = Path(__file__).resolve().parents[3]


class RunnerTests(unittest.TestCase):
    def test_grader_bundle_includes_all_run_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_01_final = root / "task_01_final.json"
            task_10_final = root / "task_10_final.json"
            task_01_final.write_text(json.dumps({"success": True, "task": 1}), encoding="utf-8")
            task_10_final.write_text(json.dumps({"success": True, "task": 10}), encoding="utf-8")

            output_path = root / "grader_bundle.json"
            write_grader_bundle(
                [
                    {"task_id": "task_01", "artifacts": {"final": str(task_01_final)}},
                    {"task_id": "task_10", "artifacts": {"final": str(task_10_final)}},
                ],
                output_path,
            )

            bundle = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(set(bundle), {"task_01", "task_10"})
            self.assertEqual(bundle["task_10"]["task"], 10)

    def test_session_summary_is_readable_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "session_summary.json"
            payload = write_session_summary(
                [
                    {
                        "session_id": "session-1",
                        "session_dir": str(root),
                        "task_id": "task_01",
                        "status": "success",
                        "step_count": 4,
                        "tool_count": 2,
                        "resource_count": 1,
                        "verification": {"ok": True},
                        "artifacts": {"final": "task_01/final.json", "trace": "task_01/trace.jsonl"},
                    },
                    {
                        "session_id": "session-1",
                        "session_dir": str(root),
                        "task_id": "task_02",
                        "status": "tool_error",
                        "step_count": 1,
                        "tool_count": 0,
                        "resource_count": 0,
                        "verification": {"ok": False},
                        "artifacts": {"final": "task_02/final.json", "trace": "task_02/trace.jsonl"},
                    },
                ],
                output_path,
                grader_bundle=root / "grader_bundle.json",
                grader_results=root / "grader_results.json",
            )

            self.assertEqual(payload["status_counts"], {"success": 1, "tool_error": 1})
            self.assertEqual(payload["metrics"]["total_llm_calls"], 5)
            self.assertEqual(payload["metrics"]["tool_call_count"], 2)
            self.assertEqual(payload["metrics"]["verification_failure_count"], 0)
            self.assertEqual(payload["metrics"]["average_steps_per_task"], 2.5)
            self.assertEqual(payload["grader_results"], str(root / "grader_results.json"))
            self.assertEqual(payload["tasks"][0]["final"], "task_01/final.json")
            self.assertTrue(output_path.exists())

    def test_session_summary_counts_trace_repairs_and_invalid_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "trace.jsonl"
            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "model_proposal", "payload": {"error": None}}),
                        json.dumps({"event": "model_proposal", "payload": {"error": "bad json"}}),
                        json.dumps({"event": "policy_decision", "payload": {"decision": {"outcome": "repair"}}}),
                    ]
                ),
                encoding="utf-8",
            )

            payload = write_session_summary(
                [
                    {
                        "session_id": "session-1",
                        "session_dir": str(root),
                        "task_id": "task_01",
                        "status": "verification_failed",
                        "step_count": 2,
                        "tool_count": 1,
                        "resource_count": 1,
                        "verification": {"ok": False},
                        "artifacts": {"final": "task_01/final.json", "trace": str(trace_path)},
                    }
                ],
                root / "session_summary.json",
            )

            self.assertEqual(payload["metrics"]["repair_count"], 1)
            self.assertEqual(payload["metrics"]["invalid_model_output_count"], 1)
            self.assertEqual(payload["metrics"]["verification_failure_count"], 1)

    def test_session_summary_counts_status_only_invalid_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "trace.jsonl"
            trace_path.write_text("", encoding="utf-8")

            payload = write_session_summary(
                [
                    {
                        "session_id": "session-1",
                        "session_dir": str(root),
                        "task_id": "task_01",
                        "status": "model_invalid_output",
                        "step_count": 1,
                        "tool_count": 0,
                        "resource_count": 0,
                        "verification": {"ok": False},
                        "artifacts": {"final": "task_01/final.json", "trace": str(trace_path)},
                    }
                ],
                root / "session_summary.json",
            )

            self.assertEqual(payload["metrics"]["invalid_model_output_count"], 1)

    def test_grade_bundle_writes_results_without_crashing_on_failed_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_path = root / "grader_bundle.json"
            output_path = root / "grader_results.json"
            bundle_path.write_text(
                json.dumps({"task_04": {"success": False, "message": "needs clarification"}}),
                encoding="utf-8",
            )

            result_path = grade_bundle(REPO_ROOT, bundle_path, output_path)

            results = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(results[0]["id"], "task_04")
            self.assertEqual(results[0]["TSR"], 0)

    def test_session_label_includes_compact_model_name(self) -> None:
        self.assertEqual(compact_model_label("claude-sonnet-4-5"), "sonnet")
        self.assertEqual(compact_model_label("claude-haiku-4-5-20251001"), "haiku")
        self.assertEqual(session_label("run-all", "sonnet"), "sonnet-run-all")


if __name__ == "__main__":
    unittest.main()
