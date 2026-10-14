# SPDX-License-Identifier: Apache-2.0
"""Safe opt-in module switchboard behavior, including disable and code isolation."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import totem_modules


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "modules.json"

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as capture:
            rc = totem_modules.main(list(args))
        return rc, capture.getvalue()

    def test_no_config_defaults_everything_off(self):
        report = totem_modules.status()
        self.assertTrue(report["modules"])
        self.assertTrue(all(not x["enabled"] for x in report["modules"]))
        self.assertEqual(report["core_safety"], "always_on")

    def test_init_writes_disabled_config_and_atomic_private_file(self):
        rc, text = self.call("init", "--config", str(self.config))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(self.config.read_text())["enabled"], [])
        self.assertEqual(json.loads(text)["status"], "PASS")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_enable_then_disable_independent_modules(self):
        self.call("init", "--config", str(self.config))
        self.call("enable", "--config", str(self.config), "onboarding")
        self.call("enable", "--config", str(self.config), "release-gate")
        self.assertEqual(set(totem_modules._read_config(self.config)),
                         {"onboarding", "release-gate"})
        self.call("disable", "--config", str(self.config), "onboarding")
        self.assertEqual(totem_modules._read_config(self.config), ["release-gate"])

    def test_disabled_module_cannot_run(self):
        self.call("init", "--config", str(self.config))
        with patch("totem_operator.main") as original:
            rc, output = self.call("run", "--config", str(self.config), "onboarding",
                                   "--", "--repo-dir", str(self.root))
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(output)["reason"], "module_disabled")
            original.assert_not_called()

    def test_unknown_module_cannot_run(self):
        self.call("init", "--config", str(self.config))
        rc, output = self.call("run", "--config", str(self.config), "remote-desktop", "--")
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["reason"], "unknown_module")

    def test_enabled_module_runs_known_entrypoint_only(self):
        self.call("init", "--config", str(self.config))
        self.call("enable", "--config", str(self.config), "onboarding")
        with patch("totem_operator.main", return_value=0) as original:
            rc, output = self.call("run", "--config", str(self.config), "onboarding",
                                   "--", "--repo-dir", str(self.root), "--entry", "main.py")
            self.assertEqual(rc, 0)
            original.assert_called_once_with(
                ["onboarding", "inspect", "--repo-dir", str(self.root), "--entry", "main.py"])

    def test_disabled_release_gate_not_silently_enabled_by_other_module(self):
        self.call("init", "--config", str(self.config))
        self.call("enable", "--config", str(self.config), "pack-review")
        rc, output = self.call("run", "--config", str(self.config), "release-gate")
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["reason"], "module_disabled")

    def test_module_disable_stops_execution_without_deleting_data(self):
        self.call("init", "--config", str(self.config))
        marker = self.root / "saved-settings.txt"
        marker.write_text("saved", encoding="utf-8")
        self.call("enable", "--config", str(self.config), "pack-review")
        self.call("disable", "--config", str(self.config), "pack-review")
        self.assertEqual(marker.read_text(encoding="utf-8"), "saved")

    def test_duplicate_and_unknown_keys_fail_closed(self):
        self.config.write_text('{"schema":1,"enabled":[],"enabled":["onboarding"]}')
        rc, output = self.call("status", "--config", str(self.config))
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["reason"], "duplicate_config_key")

    def test_bad_module_in_config_not_executed(self):
        self.config.write_text('{"schema":1,"enabled":["arbitrary-shell"]}')
        rc, output = self.call("status", "--config", str(self.config))
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["reason"], "invalid_modules_config")

    def test_symlink_config_cannot_be_enabled(self):
        target = self.root / "other.json"
        target.write_text('{"schema":1,"enabled":[]}')
        self.config.symlink_to(target)
        rc, output = self.call("enable", "--config", str(self.config), "onboarding")
        self.assertEqual(rc, 2)
        self.assertEqual(target.read_text(), '{"schema":1,"enabled":[]}')

    def test_reinit_cannot_erase_choice(self):
        self.call("init", "--config", str(self.config))
        self.call("enable", "--config", str(self.config), "onboarding")
        rc, output = self.call("init", "--config", str(self.config))
        self.assertEqual(rc, 2)
        self.assertEqual(totem_modules._read_config(self.config), ["onboarding"])

    def test_missing_config_is_not_default_allow(self):
        rc, output = self.call("run", "--config", str(self.config), "onboarding")
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["reason"], "missing_or_oversized_config")

    def test_malformed_config_rejected(self):
        self.config.write_text("not-json")
        rc, output = self.call("status", "--config", str(self.config))
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output)["status"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
