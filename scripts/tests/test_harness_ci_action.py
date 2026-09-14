from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github" / "actions" / "harness-ci" / "action.yml"
INPUT_EXPRESSION = re.compile(r"\$\{\{\s*inputs(?:\.|\[)")


class HarnessCIActionTests(unittest.TestCase):
    def test_shell_steps_do_not_interpolate_action_inputs(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        action = yaml.safe_load(text)
        steps = action["runs"]["steps"]
        shell_steps = [step for step in steps if "run" in step]

        self.assertTrue(shell_steps)
        for step in shell_steps:
            self.assertIsNone(INPUT_EXPRESSION.search(step["run"]))

        runner = next(step for step in shell_steps if step["name"] == "Run bounded Harness CI")
        self.assertEqual(
            {key: runner["env"][key] for key in (
                "REPLAY_CONTRACT", "BASE_PATH", "CANDIDATE_PATH", "POLICY_PATH", "RESULT_PATH", "COMMENT_PATH",
            )},
            {
                "REPLAY_CONTRACT": "${{ inputs.replay-contract }}",
                "BASE_PATH": "${{ inputs.base }}",
                "CANDIDATE_PATH": "${{ inputs.candidate }}",
                "POLICY_PATH": "${{ inputs.policy }}",
                "RESULT_PATH": "${{ inputs.result-path }}",
                "COMMENT_PATH": "${{ inputs.comment-path }}",
            },
        )
        for variable in ("REPLAY_CONTRACT", "BASE_PATH", "CANDIDATE_PATH", "POLICY_PATH", "RESULT_PATH", "COMMENT_PATH"):
            self.assertIn(f'"${variable}"', runner["run"])


if __name__ == "__main__":
    unittest.main()
