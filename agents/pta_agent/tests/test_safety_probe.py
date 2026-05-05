from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.pta_agent.safety_probe import run_safety_probe


REPO_ROOT = Path(__file__).resolve().parents[3]


class SafetyProbeTests(unittest.TestCase):
    def test_safety_probe_blocks_unsafe_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "safety_guardrail_proof.json"

            result = run_safety_probe(REPO_ROOT, output_path)

            self.assertTrue(output_path.exists())
            self.assertEqual(result["unsafe_bypass_count"], 0)
            self.assertEqual(result["pass_count"], result["scenario_count"])
            self.assertGreaterEqual(result["guardrail_block_count"], 1)
            self.assertGreaterEqual(result["positive_control_count"], 1)


if __name__ == "__main__":
    unittest.main()

