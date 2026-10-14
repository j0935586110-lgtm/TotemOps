# SPDX-License-Identifier: Apache-2.0
"""Offline plugin acceptance: opt-in Prism plans are NEVER runtime proof."""
import json
import unittest
from pathlib import Path

import totem_plugins
import totem_modules


class LauncherPlanTests(unittest.TestCase):
    def request(self, **changes):
        data = {"schema": 1, "launcher": "prism",
                "instance_id": "barian-test-1201",
                "server_address": "minecraft.example.org:25565",
                "sync_mode": "existing-modsync"}
        data.update(changes)
        envelope = totem_plugins.run_plugin("launcher-plan", "inspect", json.dumps(data))
        self.assertIn(envelope["status"], ("PASS", "BLOCK"), envelope)
        self.assertEqual(envelope["status"] == "BLOCK",
                         envelope["result"]["status"] == "BLOCK", envelope)
        return envelope["result"]

    def test_opt_in_plugin_is_separate_from_all_disabled_modules(self):
        report = totem_modules.status()
        self.assertTrue(all(not m["enabled"] for m in report["modules"]))
        self.assertTrue(any(p["name"] == "launcher-plan"
                            for p in totem_plugins.list_plugins()["plugins"]))

    def test_static_prism_launch_plan_has_no_execution(self):
        response = self.request()
        self.assertEqual(response["status"], "REVIEW_REQUIRED")
        self.assertEqual(response["launch_argv"],
                         ["prismlauncher", "--launch", "barian-test-1201",
                          "--server", "minecraft.example.org:25565"])
        self.assertFalse(response["game_launched"])
        self.assertFalse(response["download_performed"])
        self.assertFalse(response["configuration_written"])
        self.assertIn("signed_release_gate_ready", response["required_verifications"])

    def test_packwiz_and_automodpack_are_separate_opt_in_choices(self):
        a = self.request(sync_mode="packwiz")
        b = self.request(sync_mode="automodpack")
        self.assertIn("verified_packwiz_prelaunch_hook", a["required_verifications"])
        self.assertIn("owner_approval_to_install_both_sides", b["required_verifications"])
        self.assertNotIn("owner_approval_to_install_both_sides", a["required_verifications"])
        self.assertEqual(b["compatible"], "UNVERIFIED")

    def test_empty_sync_is_explicit_and_not_called_auto_update(self):
        r = self.request(sync_mode="none")
        self.assertIn("no_automatic_mod_sync_configured", r["required_verifications"])

    def test_missing_server_has_no_direct_join(self):
        r = self.request(server_address=None)
        self.assertEqual(len(r["launch_argv"]), 3)
        self.assertIn("server_address_required_for_direct_join", r["required_verifications"])

    def test_unsafe_commands_cannot_enter_argv(self):
        for value in ["../evil", "a&whoami", "-h", "a..b", "a|calc", "name\nxx"]:
            with self.subTest(value=value):
                self.assertEqual(self.request(instance_id=value)["status"], "BLOCK")

    def test_bad_addresses_fail_closed(self):
        for value in ["mine.example.com;calc", "https://example.com",
                      "host:0", "host:65536", "host:22:33", "host/path", ""]:
            with self.subTest(value=value):
                r = self.request(server_address=value)
                self.assertEqual(r["status"], "BLOCK")
                self.assertIsNone(r["launch_argv"])

    def test_untrusted_feed_blocks_plan(self):
        for feed in ["http://legacy.example.org/mods", "https://u.example.org/../x",
                     "https://u.example.org/file#frag", "https://u.example.org:8080/x"]:
            with self.subTest(feed=feed):
                self.assertEqual(self.request(sync_feed=feed)["status"], "BLOCK")

    def test_allowed_https_url_does_not_imply_trusted_download(self):
        r = self.request(sync_feed="https://updates.example.org/mods.json")
        self.assertEqual(r["status"], "REVIEW_REQUIRED")
        self.assertIn("verified_download_integrity", r["required_verifications"])

    def test_unknown_schema_or_updater_blocks(self):
        self.assertEqual(self.request(schema=2)["status"], "BLOCK")
        self.assertEqual(self.request(sync_mode="automagic")["status"], "BLOCK")
        self.assertEqual(self.request(extra="new_feature")["status"], "BLOCK")

    def test_wrong_command_cannot_execute(self):
        result = totem_plugins.run_plugin("launcher-plan", "install", "{}")
        self.assertEqual(result["status"], "BLOCK")

    def test_plugin_block_propagates_to_cli_exit(self):
        import contextlib
        import io
        import totem_operator

        with contextlib.redirect_stdout(io.StringIO()) as output:
            rc = totem_operator.main([
                "plugins", "run", "launcher-plan", "inspect", "--input",
                json.dumps({"schema": 2, "launcher": "prism", "instance_id": "a",
                            "sync_mode": "none"})
            ])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output.getvalue())["reason"], "plugin_reported_block")

    def test_switchboard_enable_run_disable_and_user_data_preserved(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / "modules.json"
            world = Path(home) / "level.dat"
            world.write_bytes(b"world-safe")
            def invoke(*args):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code = totem_modules.main(list(args))
                return code, json.loads(output.getvalue())
            self.assertEqual(invoke("init", "--config", str(config))[0], 0)
            payload = json.dumps({"schema": 1, "launcher": "prism",
                                  "instance_id": "test-1201", "sync_mode": "none"})
            call = ("run", "--config", str(config), "launcher-plan",
                    "--", "--input", payload)
            code, result = invoke(*call)
            self.assertEqual((code, result["reason"]), (2, "module_disabled"))
            self.assertEqual(invoke("enable", "--config", str(config),
                                    "launcher-plan")[0], 0)
            code, result = invoke(*call)
            self.assertEqual(code, 0)
            self.assertEqual(result["result"]["status"], "REVIEW_REQUIRED")
            self.assertEqual(invoke("disable", "--config", str(config),
                                    "launcher-plan")[0], 0)
            code, result = invoke(*call)
            self.assertEqual((code, result["reason"]), (2, "module_disabled"))
            self.assertEqual(world.read_bytes(), b"world-safe")


if __name__ == "__main__":
    unittest.main()
