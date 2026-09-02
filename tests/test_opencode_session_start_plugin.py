from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = REPO_ROOT / "model"
PLUGIN = MODEL_ROOT / "SCRIPTS" / "opencode_session_start_plugin.js"


def attach(brain: Path) -> None:
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "_COMMON").symlink_to(MODEL_ROOT, target_is_directory=True)


def run_plugin(directory: Path, agent_brain_home: Path) -> subprocess.CompletedProcess[str]:
    driver = """
const { BrainSessionStartPlugin } = await import(process.env.BRAIN_PLUGIN)
const plugin = await BrainSessionStartPlugin({ directory: process.env.TEST_DIRECTORY })
const first = {
  message: { id: "msg_first", sessionID: "ses_test" },
  parts: [{
    id: "part_first",
    sessionID: "ses_test",
    messageID: "msg_first",
    type: "text",
    text: "first",
  }],
}
const second = {
  message: { id: "msg_second", sessionID: "ses_test" },
  parts: [{
    id: "part_second",
    sessionID: "ses_test",
    messageID: "msg_second",
    type: "text",
    text: "second",
  }],
}
await plugin["chat.message"](
  { sessionID: "ses_test", messageID: "msg_first" },
  first,
)
await plugin["chat.message"](
  { sessionID: "ses_test", messageID: "msg_second" },
  second,
)
console.log(JSON.stringify({ first: first.parts, second: second.parts }))
"""
    env = os.environ.copy()
    env["AGENT_BRAIN_HOME"] = str(agent_brain_home)
    env["BRAIN_PLUGIN"] = str(PLUGIN)
    env["TEST_DIRECTORY"] = str(directory)
    return subprocess.run(
        ["bun", "--eval", driver],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


@unittest.skipUnless(shutil.which("bun"), "bun is required for OpenCode session start plugin tests")
class OpenCodeSessionStartPluginTests(unittest.TestCase):
    def test_injects_brain_context_only_on_first_message(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            attach(brain)

            result = run_plugin(brain, REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["first"]), 2)
        self.assertEqual(payload["first"][0]["type"], "text")
        self.assertIn("$brain", payload["first"][0]["text"])
        self.assertTrue(payload["first"][0]["id"].startswith("prt_"))
        self.assertEqual(payload["first"][0]["sessionID"], "ses_test")
        self.assertEqual(payload["first"][0]["messageID"], "msg_first")
        self.assertEqual(payload["second"], [
            {
                "id": "part_second",
                "sessionID": "ses_test",
                "messageID": "msg_second",
                "type": "text",
                "text": "second",
            }
        ])

    def test_leaves_message_unchanged_outside_a_brain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            unrelated = Path(raw) / "project"
            unrelated.mkdir()

            result = run_plugin(unrelated, REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["first"][0]["id"], "part_first")
        self.assertEqual(payload["second"][0]["id"], "part_second")

    def test_fails_safe_when_checkout_cannot_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw) / "brain"
            attach(brain)

            result = run_plugin(brain, Path(raw) / "missing-checkout")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["first"][0]["id"], "part_first")


if __name__ == "__main__":
    unittest.main()
