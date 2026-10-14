# SPDX-License-Identifier: Apache-2.0
"""AGY-native packaging contract, without touching a real Agent profile."""
from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


class AGYFirstRunTests(unittest.TestCase):
    def test_root_manifest_is_agy_native_and_no_auto_hooks(self):
        data = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "totem-ops")
        self.assertIn("antigravity.google/schemas/v1/plugin.json", data["$schema"])
        self.assertFalse((ROOT / "hooks.json").exists())
        self.assertFalse((ROOT / "mcp_config.json").exists())

    def test_skill_exists_and_references_canonical(self):
        data = (ROOT / "skills/totem-ops/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: totem-ops", data)
        self.assertIn(".agents/skills/totem-ops/SKILL.md", data)
        self.assertIn("agy plugin uninstall totem-ops", data)
        self.assertIn("mclo.gs", data)
        self.assertIn("REA", data)
        self.assertIn("PROTOCOL", data)

    def test_local_first_read_only_doctor_runs_without_agent_account(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools/totem_operator.py"), "doctor"],
            cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr[:300])
        result = json.loads(completed.stdout)
        self.assertEqual(result.get("mode"), "read_only")

    def test_docs_are_explicit_about_url_and_sandbox_limits(self):
        guide = (ROOT / "docs/AGY_FIRST_RUN.md").read_text(encoding="utf-8")
        self.assertIn("agy plugin install https://github.com/j0935586110-lgtm/TotemOps", guide)
        self.assertIn("agy plugin uninstall totem-ops", guide)
        self.assertIn("單純把網址", guide)
        self.assertIn("正式世界", guide)


if __name__ == "__main__":
    unittest.main()
