# SPDX-License-Identifier: Apache-2.0
"""Read-only, adversarial contract tests for the modsync-v2 pre-publish gate.

All JARs are synthetic ZIP fixtures created in a disposable temp directory.
No third-party source, Minecraft runtime, HTTP request or player files.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from totem_modsync_manifest import ManifestBlocked, inspect_manifest


ROOT = Path(__file__).resolve().parent.parent


def fixture_jar(path, mod_id="alpha", version="1.0", deps=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    toml = 'modLoader="javafml"\nloaderVersion="[1,)"\nlicense="MIT"\n'
    toml += f'[[mods]]\nmodId="{mod_id}"\nversion="{version}"\n'
    for name, kind in deps:
        toml += (f'[[dependencies.{mod_id}]]\nmodId="{name}"\n'
                 f'type="{kind}"\nversionRange="[1,)"\nside="BOTH"\n')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
    return path


class ModsyncManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="totem-modsync-gate-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_flat_metadata_unknown_side_and_legacy_digest(self):
        path = fixture_jar(self.root / "waystone.jar", "waystones")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["schema"], 1)
        self.assertFalse(out["release_allowed"])
        self.assertFalse(out["publication_performed"])
        self.assertEqual(out["files"][0]["execution_side"], "UNKNOWN")
        self.assertEqual(out["files"][0]["mod_ids"][0]["id"], "waystones")
        self.assertEqual(out["files"][0]["md5_legacy"], hashlib.md5(path.read_bytes()).hexdigest())
        self.assertEqual(out["files"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_duplicate_mod_id_blocks(self):
        fixture_jar(self.root / "a.jar", "alpha")
        fixture_jar(self.root / "b.jar", "alpha")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "BLOCK")
        self.assertTrue(any(f["kind"] == "duplicate_mod_id" for f in out["findings"]))

    def test_missing_required_dependency_is_review_not_proven_missing(self):
        fixture_jar(self.root / "first.jar", deps=(("balm", "required"),))
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertTrue(any(f["kind"] == "required_not_in_supplied_set" and f["to"] == "balm"
                            for f in out["findings"]))

    def test_declared_incompatible_blocks(self):
        fixture_jar(self.root / "first.jar", "first", deps=(("second", "incompatible"),))
        fixture_jar(self.root / "second.jar", "second")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "BLOCK")
        self.assertTrue(any(f["kind"] == "declared_incompatible" for f in out["findings"]))

    def test_corrupt_jar_blocks(self):
        (self.root / "bad.jar").write_bytes(b"not a zip")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["files_rejected"][0]["file"], "bad.jar")

    def test_missing_metadata_is_review_required(self):
        with zipfile.ZipFile(self.root / "unknown.jar", "w") as z:
            z.writestr("README.txt", "No mod metadata")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertTrue(any(f["kind"] == "metadata_needs_review" for f in out["findings"]))

    def test_symlink_jar_fails_closed(self):
        jar = fixture_jar(self.root / "real.jar")
        (self.root / "linked.jar").symlink_to(jar)
        with self.assertRaisesRegex(ManifestBlocked, "symlink_disallowed"):
            inspect_manifest(self.root)

    def test_symlink_inside_subdirectory_fails_closed(self):
        other = self.root / "outside"
        fixture_jar(other / "sneak.jar")
        (self.root / "mods").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ManifestBlocked, "symlink_disallowed"):
            inspect_manifest(self.root)

    def test_nested_mods_visible_not_silently_skipped(self):
        fixture_jar(self.root / "sub" / "nested.jar")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["files"][0]["path"], "sub/nested.jar")

    def test_modsync_v2_real_folders_scan_three(self):
        fixture_jar(self.root / "mods" / "server.jar", "server")
        fixture_jar(self.root / "clientmods" / "graphics.jar", "graphics")
        fixture_jar(self.root / "needmods" / "ui" / "hud.jar", "hud")
        out = inspect_manifest(self.root, layout="modsync-v2")
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(out["files"]), 3)
        self.assertEqual({x["source_folder"] for x in out["files"]},
                         {"mods", "clientmods", "needmods"})
        self.assertTrue(all(x["execution_side"] == "UNKNOWN" for x in out["files"]))
        preview = out["modsync_v2_inventory_preview"]
        self.assertEqual(len(preview["mods"]), 1)
        self.assertIn("graphics.jar", preview["clientmods"])
        self.assertIn("hud.jar", preview["needmods"]["ui"])

    def test_needsmods_is_ambiguous_and_blocked(self):
        fixture_jar(self.root / "mods" / "one.jar")
        (self.root / "needsmods").mkdir()
        with self.assertRaisesRegex(ManifestBlocked, "ambiguous_needsmods"):
            inspect_manifest(self.root, layout="modsync-v2")

    def test_filename_case_collision_blocks(self):
        fixture_jar(self.root / "foo.jar", "alpha")
        fixture_jar(self.root / "FOO.jar", "beta")
        out = inspect_manifest(self.root)
        self.assertEqual(out["status"], "BLOCK")
        self.assertTrue(any(f["kind"] == "filename_case_collision" for f in out["findings"]))

    def test_empty_folder_blocks(self):
        with self.assertRaisesRegex(ManifestBlocked, "empty_or_oversized"):
            inspect_manifest(self.root)

    def test_cli_review_is_nonzero(self):
        fixture_jar(self.root / "ok.jar")
        p = subprocess.run([sys.executable, "tools/totem_operator.py", "manifest",
                            str(self.root), "--json"],
                           cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(p.returncode, 3, p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["release_allowed"])


if __name__ == "__main__":
    unittest.main()
