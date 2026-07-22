from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from environment_profiles import provider_statuses, secret_statuses  # noqa: E402
from profile_secrets import macos_keychain_check, runtime_catalog_check  # noqa: E402


class ProfileSecretTests(unittest.TestCase):
    def profile(self) -> dict:
        return json.loads(
            (ROOT / "examples" / "profiles" / "work.json").read_text(
                encoding="utf-8"
            )
        )

    def test_environment_status_never_contains_value(self) -> None:
        secret_value = "do-not-expose-this-value"
        statuses = secret_statuses(
            self.profile(),
            environ={"EXAMPLE_TRACKER_TOKEN": secret_value},
        )
        environment = next(item for item in statuses if item.kind == "environment")

        self.assertEqual(environment.state, "available")
        self.assertNotIn(secret_value, repr(statuses))
        self.assertNotIn(secret_value, environment.detail)

    def test_empty_environment_reference_is_missing(self) -> None:
        statuses = secret_statuses(
            self.profile(),
            environ={"EXAMPLE_TRACKER_TOKEN": ""},
        )
        environment = next(item for item in statuses if item.kind == "environment")
        self.assertEqual(environment.state, "missing")

    def test_keychain_and_runtime_adapters_feed_provider_readiness(self) -> None:
        statuses = secret_statuses(
            self.profile(),
            environ={},
            keychain_check=lambda name: ("available", f"keychain reference {name}"),
            runtime_secret_check=runtime_catalog_check(
                {"example-work-session"},
                complete=True,
            ),
        )
        by_kind = {item.kind: item for item in statuses}

        self.assertEqual(by_kind["keychain"].state, "available")
        self.assertEqual(by_kind["runtime"].state, "available")

    def test_required_missing_keychain_marks_provider_missing(self) -> None:
        profile = self.profile()
        keychain = next(
            item
            for item in profile["providers"]["work-tracker"]["secret_refs"]
            if item["kind"] == "keychain"
        )
        keychain["required"] = True
        statuses = provider_statuses(
            profile,
            environ={"EXAMPLE_TRACKER_TOKEN": "present"},
            keychain_check=lambda _name: ("missing", "keychain reference missing"),
            runtime_secret_check=runtime_catalog_check(
                {"example-work-session"},
                complete=True,
            ),
        )
        provider = next(item for item in statuses if item.provider_id == "work-tracker")

        self.assertEqual(provider.state, "missing")
        self.assertNotIn("example-work-tracker", provider.detail)

    def test_macos_keychain_check_discards_all_process_streams(self) -> None:
        calls: list[tuple[list[str], dict]] = []

        def runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        state, _detail = macos_keychain_check(
            "example-work-tracker",
            platform="darwin",
            runner=runner,
        )

        self.assertEqual(state, "available")
        command, kwargs = calls[0]
        self.assertEqual(
            command,
            ["security", "find-generic-password", "-s", "example-work-tracker"],
        )
        self.assertNotIn("-w", command)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)

    def test_incomplete_runtime_catalog_does_not_claim_missing(self) -> None:
        state, _detail = runtime_catalog_check(set(), complete=False)("session")
        self.assertEqual(state, "adapter-check")


if __name__ == "__main__":
    unittest.main()
