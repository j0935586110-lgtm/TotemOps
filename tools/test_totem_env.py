# SPDX-License-Identifier: Apache-2.0
"""Machine capability gates; deterministic tests without real Docker or writes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import totem_env
from mc_operator import solve_and_verify


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "agy-sandbox"
        self.root.mkdir()
        (self.root / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n")
        self.log = self.root / "latest.log"
        self.log.write_text("test crash\n")

    def host(self, *, virt="physical_detected", rootless=False,
             mem=8192, disk=20000, cpus=4, docker=True):
        security = ["name=apparmor", "name=seccomp,profile=builtin"]
        if rootless:
            security.append("name=rootless")
        opts = {"status": "PASS", "read_only_allowed": True}
        with patch("totem_env.platform.system", return_value="Linux"), \
             patch("totem_env._virt_type", return_value=virt), \
             patch("totem_env.shutil.which", return_value="/usr/bin/docker" if docker else None), \
             patch("totem_env._memory_mb", return_value=mem), \
             patch("totem_env._disk_mb", return_value=disk), \
             patch("totem_env._cpu_count", return_value=cpus), \
             patch("totem_env.subprocess.run", return_value=subprocess.CompletedProcess(
                 ["docker"], 0, json.dumps(security), "")), \
             patch.dict("totem_env.os.environ", {"DOCKER_CONTEXT": "", "DOCKER_HOST": ""}):
            opts = totem_env.probe_environment(self.root)
        return opts

    def test_physical_rootful_docker_eligible_but_warns_about_host(self):
        report = self.host()
        self.assertTrue(report["stage_allowed"])
        self.assertTrue(report["run_allowed"])
        self.assertEqual(report["executor_tier"], "hardened_container")
        self.assertTrue(report["rootful_host_warning"])
        self.assertFalse(report["agent_tool_sandbox_verified"])

    def test_detected_vm_can_stage_and_run_with_resources(self):
        report = self.host(virt="vm_detected")
        self.assertTrue(report["stage_allowed"])
        self.assertTrue(report["run_allowed"])

    def test_rootless_physical_eligible_if_resources_allow(self):
        report = self.host(rootless=True)
        self.assertTrue(report["stage_allowed"])
        self.assertTrue(report["run_allowed"])

    def test_nested_rootful_docker_not_treated_as_trusted_host(self):
        report = self.host(virt="container_or_other")
        self.assertFalse(report["run_allowed"])
        self.assertIn("unknown_or_nested_rootful_host", report["run_blockers"])

    def test_low_ram_does_not_start_java(self):
        report = self.host(virt="vm_detected", mem=1500)
        self.assertTrue(report["stage_allowed"])
        self.assertFalse(report["run_allowed"])

    def test_low_disk_blocks_both_modes(self):
        report = self.host(virt="vm_detected", disk=900)
        self.assertFalse(report["stage_allowed"])
        self.assertFalse(report["run_allowed"])

    def test_cpu_block_for_full_run(self):
        report = self.host(virt="vm_detected", cpus=1)
        self.assertTrue(report["stage_allowed"])
        self.assertFalse(report["run_allowed"])

    def test_no_docker_blocks_execution_but_not_inspection(self):
        report = self.host(docker=False)
        self.assertTrue(report["read_only_allowed"])
        self.assertFalse(report["stage_allowed"])
        self.assertIn("docker_missing", report["stage_blockers"])

    def test_remote_docker_endpoint_is_untrusted(self):
        with patch.dict("totem_env.os.environ", {"DOCKER_HOST": "tcp://elsewhere:2375"}):
            with patch("totem_env._virt_type", return_value="vm_detected"), \
                 patch("totem_env._memory_mb", return_value=99999), \
                 patch("totem_env._disk_mb", return_value=99999), \
                 patch("totem_env.shutil.which", return_value="/usr/bin/docker"):
                report = totem_env.probe_environment(self.root)
        self.assertFalse(report["stage_allowed"])
        self.assertIn("docker_host_remote_or_unverified", report["stage_blockers"])

    def test_block_before_docker_image_inspect_or_write(self):
        def reject(*args, **kwargs):
            return {"status": "BLOCK", "blockers": ["physical_rootful_host"]}
        with patch("totem_env.preflight", side_effect=reject), \
             patch("subprocess.run") as sub, \
             patch("shutil.which", return_value="/usr/bin/docker"):
            outcome = solve_and_verify(self.log, "waystones", "1.21.1", "neoforge",
                                       self.root, execute_sandbox=True, stage_only=True)
        sub.assert_not_called()
        self.assertEqual(outcome["reason"], "environment_not_approved")
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),
                         [".agy-manager-sandbox", "latest.log"])

    def test_missing_sandbox_marker_blocks_vm(self):
        (self.root / ".agy-manager-sandbox").unlink()
        report = self.host(virt="vm_detected")
        self.assertFalse(report["run_allowed"])
        self.assertIn("sandbox_marker_not_validated", report["run_blockers"])

    def test_cgroup_cpu_quota_limits_capacity(self):
        with patch("totem_env.os.cpu_count", return_value=8), \
             patch("totem_env.Path.read_text", return_value="150000 100000"):
            self.assertEqual(totem_env._cpu_count(), 1)

    def test_cgroup_memory_restricts_visible_host_memory(self):
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data="MemAvailable: 2097152 kB\n")), \
             patch("totem_env.Path.read_text", side_effect=[
                 "1073741824", "805306368"]):
            self.assertEqual(totem_env._memory_mb(), 256)

    def test_plan_only_ignores_host_checks(self):
        with patch("totem_env.preflight") as gate:
            outcome = solve_and_verify(self.log, "waystones", "1.21.1",
                                       "neoforge", None)
        gate.assert_not_called()
        self.assertEqual(outcome["status"], "PLAN_ONLY")


if __name__ == "__main__":
    unittest.main()
