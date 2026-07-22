from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "profiles"
SCHEMAS = ROOT / "docs" / "schemas"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RuntimeProfileContractTests(unittest.TestCase):
    def test_profile_schemas_are_valid_json(self) -> None:
        for name in (
            "environment-profile-v1.schema.json",
            "profile-selection-v1.schema.json",
        ):
            with self.subTest(schema=name):
                schema = load_json(SCHEMAS / name)
                self.assertEqual(
                    schema["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertFalse(schema["additionalProperties"])

    def test_sanitized_example_selection_references_existing_profiles(self) -> None:
        selection = load_json(EXAMPLES / "environment.json")
        profiles = {
            path.stem: load_json(path)
            for path in EXAMPLES.glob("*.json")
            if path.name != "environment.json"
        }

        self.assertEqual(selection["schema_version"], 1)
        self.assertIn(selection["default_profile"], profiles)
        for rule in selection["project_rules"]:
            self.assertIn(rule["profile"], profiles)

    def test_sanitized_example_capability_routes_are_resolvable(self) -> None:
        profile = load_json(EXAMPLES / "work.json")
        providers = profile["providers"]

        for capability, route in profile["capability_routes"].items():
            self.assertTrue(route, capability)
            for provider_id in route:
                self.assertIn(provider_id, providers, capability)
                provider = providers[provider_id]
                if provider["kind"] != "manual":
                    self.assertIn(capability, provider["operations"], provider_id)

        tracking = profile["issue_tracking"]
        self.assertIn(tracking["provider"], providers)
        self.assertIn(tracking["default_project"], tracking["project_keys"])

        overlays = profile["runtime_overlays"]
        self.assertTrue(overlays)
        for overlay in overlays:
            self.assertFalse(Path(overlay["path"]).is_absolute())
            self.assertFalse(Path(overlay["target"]).is_absolute())
            self.assertNotIn("..", Path(overlay["path"]).parts)
            self.assertNotIn("..", Path(overlay["target"]).parts)

if __name__ == "__main__":
    unittest.main()
