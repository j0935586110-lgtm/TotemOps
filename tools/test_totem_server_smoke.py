# SPDX-License-Identifier: Apache-2.0
"""Synthetic negative acceptance for read-only existing-server smoke probe."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import totem_server_smoke as smoke


class SmokeProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "totemops-test-e2e"
        self.mods = self.root / "server" / "mods"
        self.mods.mkdir(parents=True)
        with zipfile.ZipFile(self.mods / "demo.jar", "w") as z:
            z.writestr("META-INF/neoforge.mods.toml",
                       'modLoader="javafml"\nloaderVersion="[1,)"\nlicense="MIT"\n'
                       '[[mods]]\nmodId="demo"\nversion="1.0"\n')
        self.metadata = {
            "Name":"/tot-e2e-test-01", "State":{"Running":True,"Health":{"Status":"healthy"}},
            "NetworkSettings":{"Ports":{"25565/tcp":None},
                               "Networks":{"tot-e2e-test-net":{}}},
            "Mounts":[{"Destination":"/data", "Source":str(self.root / "server")}],
        }
        self.logs = ('Found mod file "demo.jar"\n'
                     'NeoForge mod loading, version 21.1.259, for MC 1.21.1\n'
                     'Starting minecraft server version 1.21.1\n'
                     'Done (10.10s)! For help, type "help"\n')
        self.internal = "true"

    def fake_docker(self,*args,**kwargs):
        if args[0] == "inspect":
            return json.dumps([self.metadata])
        if args[0] == "network":
            return self.internal
        if args[0] == "logs":
            return self.logs
        raise AssertionError("Unexpected Docker action: " + str(args))

    def run_probe(self):
        with patch.object(smoke, "_docker", side_effect=self.fake_docker):
            return smoke.inspect_server(self.mods,sandbox_root=self.root,
                                        container="tot-e2e-test-01",
                                        minecraft="1.21.1",neoforge="21.1.259")

    def test_genuine_boot_receipt_never_claims_gameplay(self):
        result = self.run_probe()
        self.assertEqual(result["status"],"REVIEW_REQUIRED")
        self.assertTrue(result["server_boot_smoke_verified"])
        self.assertFalse(result["release_allowed"])
        self.assertFalse(result["gameplay_verified"])
        self.assertFalse(result["world_modified"])

    def test_published_port_blocks(self):
        self.metadata["NetworkSettings"]["Ports"]["25565/tcp"] = [{"HostPort":"25565"}]
        with self.assertRaisesRegex(smoke.SmokeBlocked,"published_ports_forbidden"):
            self.run_probe()

    def test_non_internal_network_blocks(self):
        self.internal = "false"
        with self.assertRaisesRegex(smoke.SmokeBlocked,"docker_network_not_internal"):
            self.run_probe()

    def test_failed_health_blocks(self):
        self.metadata["State"]["Health"]["Status"] = "unhealthy"
        with self.assertRaisesRegex(smoke.SmokeBlocked,"container_not_healthy"):
            self.run_probe()

    def test_version_mismatch_blocks(self):
        self.logs = self.logs.replace("21.1.259","21.1.240")
        with self.assertRaisesRegex(smoke.SmokeBlocked,"loader_version_or_game_version_mismatch"):
            self.run_probe()

    def test_no_done_marker_blocks(self):
        self.logs = self.logs.replace("Done (10.10s)!", "Still loading")
        with self.assertRaisesRegex(smoke.SmokeBlocked,"neoforge_or_done_marker_missing"):
            self.run_probe()

    def test_fatal_after_loader_blocks(self):
        self.logs += "Exception in server tick loop\n"
        with self.assertRaisesRegex(smoke.SmokeBlocked,"fatal_server_log_after_latest_loader_start"):
            self.run_probe()

    def test_mod_not_discovered_blocks(self):
        self.logs = self.logs.replace('Found mod file "demo.jar"', 'no mod files detected')
        with self.assertRaisesRegex(smoke.SmokeBlocked,"mod_discovery_log_missing"):
            self.run_probe()

    def test_container_name_not_marked_blocks_without_docker_calls(self):
        with self.assertRaisesRegex(smoke.SmokeBlocked,"container_name_not_marked_disposable"):
            smoke.inspect_server(self.mods,sandbox_root=self.root,
                                 container="production-minecraft",
                                 minecraft="1.21.1",neoforge="21.1.259")


if __name__ == "__main__":
    unittest.main()
