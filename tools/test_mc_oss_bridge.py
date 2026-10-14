# SPDX-License-Identifier: Apache-2.0
"""Unit tests for read-only orchestration around established OSS commands."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from mc_oss_bridge import MAX_OUTPUT, doctor, plan, status


class MinecraftOSSBridgeTests(unittest.TestCase):
    @patch("mc_oss_bridge._binary", return_value="/sandbox/mc-monitor")
    @patch("mc_oss_bridge.subprocess.run")
    def test_status_success_real_protocol_json(self, run, binary):
        run.return_value = subprocess.CompletedProcess([], 0, '{"version":{"name":"1.21.1"},"players":{"online":0}}', "")
        result = status("127.0.0.1", 25565)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["code"], "PASS")
        self.assertEqual(result["data"]["version"]["name"], "1.21.1")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/sandbox/mc-monitor", "status", "-host", "127.0.0.1", "-port", "25565", "-json", "-timeout", "4s"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 9)

    @patch("mc_oss_bridge._binary", return_value="/sandbox/mc-monitor")
    @patch("mc_oss_bridge.subprocess.run")
    def test_status_negative_not_false_positive(self, run, _binary):
        run.return_value = subprocess.CompletedProcess([], 1, "", "dial tcp: connection refused")
        result = status("localhost", 25565)
        self.assertTrue(result["probe_completed"])
        self.assertFalse(result["healthy"])
        self.assertEqual(result["exit"], 1)

    @patch("mc_oss_bridge.subprocess.run")
    def test_remote_host_refused_before_any_execution(self, run):
        result = status("example.invalid", 25565)
        self.assertEqual(result["reason"], "target_not_allowlisted")
        run.assert_not_called()

    @patch("mc_oss_bridge.subprocess.run")
    def test_bad_port_refused(self, run):
        result = status("127.0.0.1", 0)
        self.assertEqual(result["reason"], "invalid_port")
        run.assert_not_called()

    @patch("mc_oss_bridge._binary", return_value=None)
    def test_missing_tool_does_not_fake_success(self, _binary):
        result = status("127.0.0.1", 25565)
        self.assertEqual(result["code"], "BLOCK")
        self.assertEqual(result["reason"], "mc_monitor_missing")

    @patch("mc_oss_bridge._binary", return_value="/sandbox/mc-monitor")
    @patch("mc_oss_bridge.subprocess.run")
    def test_timeout_block(self, run, _binary):
        run.side_effect = subprocess.TimeoutExpired(cmd=["mc-monitor"], timeout=9)
        result = status("127.0.0.1", 25565)
        self.assertEqual(result["code"], "BLOCK")
        self.assertEqual(result["reason"], "tool_timeout")

    @patch("mc_oss_bridge._binary", return_value="/sandbox/mc-monitor")
    @patch("mc_oss_bridge.subprocess.run")
    def test_invalid_json_block(self, run, _binary):
        run.return_value = subprocess.CompletedProcess([], 0, "ready", "")
        result = status("127.0.0.1", 25565)
        self.assertEqual(result["reason"], "invalid_status_json")

    @patch("mc_oss_bridge._binary", return_value=None)
    def test_plan_never_downloads_or_modifies(self, _binary):
        result = plan("modrinth-dependencies")
        self.assertEqual(result["code"], "PLAN_ONLY")
        self.assertEqual(result["recommended_tool"], "mc-image-helper")
        self.assertFalse(result["available_here"])
        self.assertEqual(result["changes"], [])

    def test_plan_known_options(self):
        self.assertEqual(plan("client-sync")["recommended_tool"], "AutoModpack")
        self.assertEqual(plan("server-status")["recommended_tool"], "mc-monitor")

    @patch("mc_oss_bridge._binary", return_value=None)
    def test_doctor_probes_no_network_or_mutation(self, _binary):
        result = doctor()
        self.assertEqual(result["mode"], "read_only")
        self.assertEqual(result["tools"]["MCSManager"]["available"], False)


if __name__ == "__main__":
    unittest.main()
