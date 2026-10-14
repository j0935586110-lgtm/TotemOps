# SPDX-License-Identifier: Apache-2.0
"""Offline RED/GREEN release-inspection fixtures. Filesystem is never changed."""
from __future__ import annotations
import json
import stat
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from mc_package_inspector import InputBlocked
from totem_release import inspect_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def manifest(self):
        return {
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": "Test MC8 Pack", "version": "3.5.0",
            "minecraft": {"version": "1.21.1",
                          "modLoaders": [{"id": "neoforge-21.1.250", "primary": True}]},
            "files": [
                {"projectID": 11, "fileID": 21, "required": True},
                {"projectID": 12, "fileID": 22, "required": False},
                {"projectID": 13, "fileID": 23, "required": False},
            ],
            "overrides": "overrides",
        }

    def pack(self, *, extras=None, manifest=None):
        path = self.root / "client.zip"
        with ZipFile(path, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest or self.manifest()))
            z.writestr("overrides/mods/newmod.jar", b"new")
            z.writestr("overrides/servers.dat", b"serverA")
            for name, data in (extras or {}).items():
                z.writestr(name, data)
        return path

    def update(self, *, extras=None):
        path = self.root / "update.zip"
        with ZipFile(path, "w") as z:
            z.writestr("MC8 v3.5.0 update/Readme.md",
                       "1. 複製檔案\n2. 移除 oldmod.jar\n3. 移除舊的MultiMine-1.2.0.jar\n")
            z.writestr("MC8 v3.5.0 update/mods/newmod.jar", b"new")
            z.writestr("MC8 v3.5.0 update/servers.dat", b"serverB")
            for name, data in (extras or {}).items():
                z.writestr(name, data)
        return path

    def test_makes_owner_reviewable_plan_but_no_install(self):
        result = inspect_release(self.pack(), self.update())
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["pack"]["sha256"]), 64)
        self.assertEqual(len(result["update"]["sha256"]), 64)
        self.assertEqual(result["evidence"], "PACKAGING_STATIC_ONLY")
        self.assertEqual(result["pack"]["required_external_files"], 1)
        self.assertEqual(result["pack"]["optional_external_files"], 2)
        self.assertEqual(len(result["optional_decisions"]["entries"]), 2)
        self.assertEqual(result["update"]["copy_operations"], 2)
        self.assertEqual(len(result["update"]["manual_deletions"]), 2)
        self.assertIn("mods/oldmod.jar", result["update"]["manual_deletions"])
        self.assertIn("mods/MultiMine-1.2.0.jar", result["update"]["manual_deletions"])
        self.assertEqual(result["update"]["comparison"]["identical_to_full_overrides"], 1)
        self.assertEqual(result["update"]["comparison"]["different_from_full_overrides"], 1)
        self.assertFalse(result["write_performed"])
        self.assertFalse(result["updates_applied"])
        self.assertFalse(result["game_launched"])
        self.assertEqual([r["result"] for r in result["release_checks"][-1:]],
                         ["ACTION_REQUIRED"])

    def test_does_not_touch_existing_world_or_mods(self):
        folder = self.root / "live-game"
        folder.mkdir()
        jar = folder / "oldmod.jar"
        jar.write_bytes(b"keep-this")
        inspect_release(self.pack(), self.update())
        self.assertEqual(jar.read_bytes(), b"keep-this")

    def test_no_update_also_review_required(self):
        result = inspect_release(self.pack())
        self.assertIsNone(result["update"])
        self.assertEqual(result["optional_decisions"]["count"], 2)
        self.assertFalse(result["pack"]["external_files_downloaded"])

    def test_rejects_zip_path_traversal(self):
        with self.assertRaisesRegex(InputBlocked, "unsafe_release_archive_path"):
            inspect_release(self.pack(extras={"../escape": b"bad"}))

    def test_rejects_windows_backslash_path(self):
        with self.assertRaisesRegex(InputBlocked, "unsafe_release_archive_path"):
            inspect_release(self.pack(extras={r"..\bad.jar": b"bad"}))

    def test_rejects_casefold_duplicates(self):
        with self.assertRaisesRegex(InputBlocked, "release_duplicate_casefold_path"):
            inspect_release(self.pack(extras={"OVERRIDES/SERVERS.DAT": b"dupe"}))

    def test_rejects_update_traversal(self):
        with self.assertRaisesRegex(InputBlocked, "unsafe_release_archive_path"):
            inspect_release(self.pack(), self.update(extras={"../../mods/evil.jar": b"bad"}))

    def test_rejects_zip_symlink(self):
        path = self.pack()
        link = ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(path, "a") as z:
            z.writestr(link, "../private")
        with self.assertRaisesRegex(InputBlocked, "release_symlink_member"):
            inspect_release(path)

    def test_rejects_invalid_curseforge_manifest(self):
        manifest = self.manifest()
        manifest["manifestType"] = "random-zip"
        with self.assertRaisesRegex(InputBlocked, "unsupported_curseforge_manifest"):
            inspect_release(self.pack(manifest=manifest))

    def test_rejects_linked_package(self):
        path = self.pack()
        link = self.root / "symlink.zip"
        link.symlink_to(path)
        with self.assertRaisesRegex(InputBlocked, "invalid_release_file"):
            inspect_release(link)


if __name__ == "__main__":
    unittest.main()
