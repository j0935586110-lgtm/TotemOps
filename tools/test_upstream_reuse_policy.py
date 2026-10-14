# SPDX-License-Identifier: Apache-2.0
"""Guard TotemOps' reuse-first policy and honest reproducibility claims (offline)."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "evidence" / "upstream-reuse-2472" / "case.json"


class UpstreamReusePolicyTests(unittest.TestCase):
    def test_machine_readable_trial_is_pinned(self):
        receipt = json.loads(CASE.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["decision"], "REUSE_UPSTREAM_PR_TESTS_BEFORE_CUSTOM_PATCH")
        self.assertEqual(receipt["issue"]["number"], 2472)
        self.assertEqual(receipt["upstream_solution"]["head_sha"],
                         "78959a88a8f6a34ba4157e4bb651b4f000f7edb7")
        self.assertEqual(receipt["local_baseline"]["official_junit"]["tests"], 77)
        self.assertEqual(receipt["local_baseline"]["official_junit"]["failures"], 0)

    def test_no_version_or_gameplay_overclaim(self):
        receipt = json.loads(CASE.read_text(encoding="utf-8"))
        self.assertEqual(receipt["upstream_solution"]["minecraft"], "26.2")
        self.assertEqual(receipt["local_baseline"]["branch"], "1.21.1")
        self.assertEqual(receipt["naive_patch_control"]["status"],
                         "REJECTED_AFTER_REUSE_REVIEW")
        self.assertEqual(receipt["naive_patch_control"]["existing_junit"]["tests"], 77)
        scope = receipt["scope"]
        for key in ("pr_tests_run_locally", "pr_26_2_backport_to_1_21_1",
                    "in_game_key_modifier_fix_verified", "production_world_modified"):
            self.assertIs(scope[key], False, key)
        self.assertEqual(receipt["local_baseline"]["real_gui_reproduction"], "NOT_RUN")

    def test_both_agent_skills_require_existing_pr_search(self):
        for relative in ("skills/totem-ops/SKILL.md",
                         ".agents/skills/totem-ops/SKILL.md"):
            doc = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("PR", doc)
            self.assertIn("UPSTREAM_REUSE_TRIAL_2472.md", doc)
            self.assertIn("baseline", doc.lower())
            self.assertIn("GAMEPLAY_VERIFIED", doc)
            self.assertIn("sandbox", doc.lower())

    def test_documentation_references_actual_external_case(self):
        doc = (ROOT / "docs" / "UPSTREAM_REUSE_TRIAL_2472.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/neoforged/NeoForge/issues/2472", doc)
        self.assertIn("https://github.com/neoforged/NeoForge/pull/3331", doc)
        self.assertIn(":neoforge:setup", doc)
        self.assertIn(":tests:junitTest", doc)


if __name__ == "__main__":
    unittest.main()
