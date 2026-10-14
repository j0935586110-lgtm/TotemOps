# SPDX-License-Identifier: Apache-2.0
"""CurseForge Minecraft modpack metadata used by the real MC8 player workflow."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mc_package_inspector import InputBlocked, inspect_one, inspect_path


class CurseForgePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make(self, data):
        path = self.root / "MC8-client.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(data))
            z.writestr("overrides/servers.dat", b"fake-test-only")
        return path

    def sample(self):
        return {
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": "Yuan MC8 Client Prod",
            "version": "3.5.0",
            "author": "Yuan Chiu",
            "minecraft": {
                "version": "1.21.1",
                "modLoaders": [{"id": "neoforge-21.1.250", "primary": True}],
            },
            "files": [
                {"projectID": 101, "fileID": 201, "required": True},
                {"projectID": 102, "fileID": 202, "required": False},
            ],
            "overrides": "overrides",
        }

    def test_valid_curseforge_returns_useful_player_preflight(self):
        result = inspect_path(self.make(self.sample()))
        pack = result["packages"][0]["pack"]
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(pack["format"], "curseforge")
        self.assertEqual(pack["minecraft"], "1.21.1")
        self.assertIn("neoforge-21.1.250", pack["mod_loaders"])
        self.assertEqual(pack["files_count"], 2)
        self.assertEqual(pack["required_files"], 1)
        self.assertEqual(pack["optional_files"], 1)
        self.assertTrue(pack["external_files_require_launcher_download"])
        self.assertFalse(pack["game_test_executed"])

    def test_malicious_override_path_rejected(self):
        m = self.sample()
        m["overrides"] = "../danger"
        with self.assertRaises(InputBlocked):
            inspect_one(self.make(m))

    def test_bad_file_reference_rejected(self):
        m = self.sample()
        m["files"] = [{"projectID": -1, "fileID": 42, "required": True}]
        with self.assertRaises(InputBlocked):
            inspect_one(self.make(m))

    def test_non_curseforge_json_not_misparsed(self):
        m = self.sample()
        m["manifestType"] = "notMinecraft"
        with self.assertRaises(InputBlocked):
            inspect_one(self.make(m))


if __name__ == "__main__":
    unittest.main()
