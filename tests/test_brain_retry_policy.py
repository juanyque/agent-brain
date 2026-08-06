from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "brain" / "SKILL.md"
CONSTRAINTS = ROOT / "skills" / "brain" / "references" / "constraints.md"
HEADING = "### Failure recovery and retries"
NEXT_LINE = "- Every apply-mode script run writes a `.log` file"


def retry_policy(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.index(NEXT_LINE, start)
    return text[start:end].strip()


class BrainRetryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = retry_policy(CONSTRAINTS)

    def test_same_failed_command_is_prohibited(self) -> None:
        self.assertIn(
            "Repeat the same failed command with the same inputs, parameters, and strategy | Prohibited",
            self.policy,
        )

    def test_stale_patch_context_may_be_reread_and_corrected(self) -> None:
        self.assertIn(
            "A patch fails because its context is stale; the target is reread and the patch is rebuilt against current content | Allowed when every corrected-retry condition holds",
            self.policy,
        )

    def test_diagnosed_syntax_error_may_be_corrected(self) -> None:
        self.assertIn(
            "A syntax or formatting error is diagnosed and the invocation is corrected | Allowed when every corrected-retry condition holds",
            self.policy,
        )

    def test_third_distinct_failed_strategy_requires_stop(self) -> None:
        self.assertIn(
            "A third distinct consecutive strategy fails without material progress | Stop, summarize the three strategies, and ask for direction",
            self.policy,
        )

    def test_partial_or_ambiguous_state_requires_immediate_stop(self) -> None:
        self.assertIn(
            "The failed operation may have produced partial or ambiguous state | Stop immediately and inspect or request direction; do not retry",
            self.policy,
        )

    def test_skill_routes_failure_handling_to_constraints_reference(self) -> None:
        self.assertIn(
            "| Brain write authorization, apply-mode gates, `_STAGING`, skip-full-reorder, or tool failure handling | `references/constraints.md` |",
            SKILL.read_text(encoding="utf-8"),
        )

    def test_retry_policy_has_one_canonical_source(self) -> None:
        self.assertNotIn(HEADING, SKILL.read_text(encoding="utf-8"))
        self.assertEqual(1, CONSTRAINTS.read_text(encoding="utf-8").count(HEADING))

    def test_retry_does_not_expand_authority_or_risk(self) -> None:
        required_guards = (
            "the original operation was already authorized",
            "no dangerous partial state or ambiguous external state",
            "the cause is understood",
            "same scope, permissions, and risk level",
            "the retry is not destructive",
            "must not introduce an unauthorized write",
            "bypass an approval gate",
            "expand the target or scope",
        )
        for guard in required_guards:
            with self.subTest(guard=guard):
                self.assertIn(guard, self.policy)


if __name__ == "__main__":
    unittest.main()
