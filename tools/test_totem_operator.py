# SPDX-License-Identifier: Apache-2.0
"""Portable CLI, opt-in plugin, and legacy command compatibility tests."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import totem_operator
import totem_plugins


class TotemTests(unittest.TestCase):
    def test_discovery_does_not_execute(self):
        listing = totem_plugins.list_plugins()
        self.assertEqual(listing["status"], "PASS")
        self.assertIn("example-info", [item["name"] for item in listing["plugins"]])

    def test_opt_in_example_plugin(self):
        r = totem_plugins.run_plugin("example-info", "echo", '{"message":"hello"}')
        self.assertEqual(r["status"], "PASS")
        self.assertFalse(r["trusted"])
        self.assertEqual(r["result"]["echo"], "hello")

    def test_plugin_cannot_auto_run_from_list(self):
        r = totem_plugins.list_plugins()
        self.assertNotIn("result", r)

    def test_unknown_plugin_is_block(self):
        r = totem_plugins.run_plugin("nonexistent", "about", "{}")
        self.assertEqual(r["status"], "BLOCK")

    def test_command_restriction(self):
        r = totem_plugins.run_plugin("example-info", "delete-world", "{}")
        self.assertEqual(r["reason"], "unknown_plugin_command")

    def test_json_payload_restriction(self):
        r = totem_plugins.run_plugin("example-info", "echo", "not-json")
        self.assertEqual(r["status"], "BLOCK")

    def test_entry_cli_plugin_list(self):
        from io import StringIO
        from contextlib import redirect_stdout
        s = StringIO()
        with redirect_stdout(s):
            rc = totem_operator.main(["plugins", "list"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(s.getvalue())["plugins"][0]["name"], "example-info")

    def test_entry_cli_legacy_doctor(self):
        from contextlib import redirect_stdout
        from io import StringIO
        s = StringIO()
        with redirect_stdout(s):
            rc = totem_operator.main(["doctor"])
        self.assertEqual(rc, 0)
        self.assertIn("tools", json.loads(s.getvalue()))

    def test_entry_cli_legacy_plan_deploy(self):
        from contextlib import redirect_stdout
        from io import StringIO
        s = StringIO()
        with redirect_stdout(s):
            rc = totem_operator.main(["plan-deploy", "--version", "1.21.1",
                                      "--loader", "NEOFORGE", "--memory", "8G"])
        out = json.loads(s.getvalue())
        self.assertEqual(rc, 0)
        self.assertFalse(out["deployed"])

    def test_invalid_symlink_folder_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "malicious").symlink_to(Path(__file__).resolve().parent)
            with patch.object(totem_plugins, "PLUGINS", root):
                result = totem_plugins.run_plugin("malicious", "echo", "{}")
            self.assertEqual(result["status"], "BLOCK")

    def test_plugin_entry_cannot_traverse(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "test-plugin"
            p.mkdir()
            (p / "plugin.json").write_text(json.dumps({
                "name": "test-plugin", "entry": ["python3", "../outside.py"],
                "commands": ["run"]
            }))
            with patch.object(totem_plugins, "PLUGINS", root):
                result = totem_plugins.run_plugin("test-plugin", "run", "{}")
            self.assertEqual(result["status"], "BLOCK")

    def test_quick_diagnose_is_bounded_and_read_only(self):
        from io import StringIO
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "latest.log"
            log.write_text("java.lang.NoClassDefFoundError: net/minecraft/client/Minecraft\n")
            output = StringIO()
            with redirect_stdout(output):
                code = totem_operator.main(["quick", "diagnose", str(log)])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertLess(len(output.getvalue().encode()), 1200)
            self.assertIsNone(result["confirmed_root_cause"])
            self.assertEqual(result["clues"][0]["status"], "SUSPECTED")

    def test_quick_inspect_shows_max_three(self):
        from io import StringIO
        from contextlib import redirect_stdout
        fixture = {"status": "PASS", "analyzed": 30,
                   "mods": [{"id": f"mod-{x}", "loader": "neoforge"} for x in range(30)],
                   "findings": [{"kind": "dependency_missing"}] * 20}
        with patch("mc_operator.summarize_package", return_value=fixture):
            output = StringIO()
            with redirect_stdout(output):
                code = totem_operator.main(["quick", "inspect", "mods/"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(len(data["mods"]), 3)
        self.assertEqual(len(data["findings"]), 3)
        self.assertTrue(data["truncated"])
        self.assertFalse(data["verified_compatible"])
        self.assertLess(len(output.getvalue().encode()), 1200)

    def test_preflight_is_read_only(self):
        from io import StringIO
        from contextlib import redirect_stdout
        fake = {"status": "PASS", "run_allowed": False,
                "stage_allowed": False, "no_actions_executed": True}
        with patch("totem_env.probe_environment", return_value=fake):
            output = StringIO()
            with redirect_stdout(output):
                code = totem_operator.main(["preflight"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), fake)

    def test_project_default_low_trust_opencode_policy(self):
        root = Path(__file__).resolve().parent.parent
        cfg = json.loads((root / "opencode.json").read_text())
        self.assertEqual(cfg["default_agent"], "plan")
        self.assertNotIn("permission", cfg)  # v1/v2 permission schemas differ
        v1 = json.loads((root / "examples/opencode-v1-readonly.json").read_text())
        self.assertEqual(v1["permission"]["edit"], "deny")
        self.assertEqual(v1["permission"]["bash"], "ask")
        v2 = json.loads((root / "examples/opencode-v2-readonly.json").read_text())
        self.assertTrue(any(r["action"] == "edit" and r["effect"] == "deny"
                            for r in v2["permissions"]))

    def test_agent_tool_sandbox_templates_do_not_escalate(self):
        root = Path(__file__).resolve().parent.parent
        claw = json.loads((root / "examples/openclaw-sandbox-all.json").read_text())
        sandbox = claw["agents"]["defaults"]["sandbox"]
        self.assertEqual(sandbox["mode"], "all")
        self.assertEqual(sandbox["scope"], "session")
        self.assertEqual(sandbox["workspaceAccess"], "ro")
        self.assertEqual(sandbox["docker"]["capDrop"], ["ALL"])
        self.assertEqual(sandbox["docker"]["network"], "none")
        self.assertFalse(claw["tools"]["elevated"]["enabled"])
        self.assertEqual(claw["tools"]["exec"]["host"], "sandbox")
        hermes = (root / "examples/hermes-sandbox-docker.yaml").read_text()
        self.assertIn("backend: docker", hermes)
        self.assertIn("container_persistent: false", hermes)
        self.assertIn("docker_network: false", hermes)
        self.assertIn("docker_forward_env: []", hermes)

    def test_name_slash_blocked(self):
        r = totem_plugins.run_plugin("../bad", "about", "{}")
        self.assertEqual(r["reason"], "invalid_plugin_name")


if __name__ == "__main__":
    unittest.main()
