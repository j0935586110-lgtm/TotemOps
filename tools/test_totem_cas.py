# SPDX-License-Identifier: Apache-2.0
"""TotemOps CAS Lite tests, with repeatable tiny JAR fixtures and no network."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from totem_cas import (CASRejected, import_receipt, restore_receipt,
                       stats, verify_receipt)


class CASTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "agy-sandbox"
        self.root.mkdir()
        (self.root / ".agy-manager-sandbox").write_bytes(b"AGY_TEST_SANDBOX_V1\n")
        self.first = self.root / "pack-one" / "mods"
        self.first.mkdir(parents=True)
        self.one = b"this-is-balm-jar-not-executable"
        self.two = b"this-is-waystones-jar-not-executable"
        (self.first / "balm.jar").write_bytes(self.one)
        (self.first / "waystones.jar").write_bytes(self.two)
        self.receipt = {
            "status": "STAGED_ONLY",
            "candidate": {"project": "waystones", "version_id": "6Z6MQ6os",
                          "loader": "neoforge", "game_version": "1.21.1"},
            "staged_jars": [
                {"name": "balm.jar", "sha256": hashlib.sha256(self.one).hexdigest()},
                {"name": "waystones.jar", "sha256": hashlib.sha256(self.two).hexdigest()},
            ],
        }

    def test_fresh_import_verify_and_restore(self):
        stored = import_receipt(self.root, self.first, self.receipt)
        self.assertEqual(stored["new_blobs"], 2)
        self.assertEqual(verify_receipt(self.root, self.receipt)["status"], "CAS_VALID")
        dst = self.root / "pack-two" / "mods"
        result = restore_receipt(self.root, dst, self.receipt, 15)
        self.assertEqual(result["status"], "CAS_RESTORED")
        self.assertEqual((dst / "balm.jar").read_bytes(), self.one)
        self.assertNotEqual((dst / "balm.jar").stat().st_ino, (self.first / "balm.jar").stat().st_ino)
        self.assertEqual(stats(self.root)["blobs"], 2)

    def test_reimport_deduplicates(self):
        import_receipt(self.root, self.first, self.receipt)
        again = import_receipt(self.root, self.first, self.receipt)
        self.assertEqual(again["new_blobs"], 0)
        self.assertEqual(again["existing_blobs"], 2)
        self.assertEqual(stats(self.root)["manifests"], 1)

    def test_two_packs_share_balm(self):
        import_receipt(self.root, self.first, self.receipt)
        second = dict(self.receipt)
        second["candidate"] = {**self.receipt["candidate"], "project": "second-pack"}
        second["staged_jars"] = [self.receipt["staged_jars"][0]]
        out = import_receipt(self.root, self.first, second)
        self.assertEqual(out["new_blobs"], 0)
        self.assertEqual(out["existing_blobs"], 1)
        s = stats(self.root)
        self.assertEqual((s["blobs"], s["manifests"]), (2, 2))
        self.assertEqual(s["deduplicated_bytes"], len(self.one))

    def test_broken_blob_refuses_to_restore(self):
        import_receipt(self.root, self.first, self.receipt)
        sha = self.receipt["staged_jars"][0]["sha256"]
        blob = self.root / ".totemops-cas" / "objects" / "sha256" / sha[:2] / sha
        blob.write_bytes(b"corrupt")
        with self.assertRaisesRegex(CASRejected, "cas_blob_corrupt"):
            restore_receipt(self.root, self.root / "restored", self.receipt, 15)
        self.assertFalse((self.root / "restored").exists())

    def test_missing_blob_is_miss(self):
        import_receipt(self.root, self.first, self.receipt)
        sha = self.receipt["staged_jars"][0]["sha256"]
        (self.root / ".totemops-cas" / "objects" / "sha256" / sha[:2] / sha).unlink()
        self.assertEqual(restore_receipt(self.root, self.root / "restored", self.receipt)["status"], "MISS")

    def test_manifest_is_exact_pack_identity(self):
        import_receipt(self.root, self.first, self.receipt)
        modified = dict(self.receipt)
        modified["candidate"] = {**self.receipt["candidate"], "game_version": "1.21.2"}
        self.assertEqual(verify_receipt(self.root, modified)["status"], "MISS")

    def test_download_preferred_when_measured_faster(self):
        import_receipt(self.root, self.first, self.receipt)
        dest = self.root / "restored"
        result = restore_receipt(self.root, dest, self.receipt, 0.00001)
        self.assertEqual(result["status"], "DOWNLOAD")
        self.assertFalse(dest.exists())

    def test_refuse_protected_source(self):
        world = self.root / "world" / "mods"
        world.mkdir(parents=True)
        for f in self.first.iterdir():
            (world / f.name).write_bytes(f.read_bytes())
        with self.assertRaisesRegex(CASRejected, "protected_path"):
            import_receipt(self.root, world, self.receipt)

    def test_refuse_traversal_name(self):
        self.receipt["staged_jars"][0]["name"] = "../world/level.dat"
        with self.assertRaisesRegex(CASRejected, "invalid_stage_name"):
            import_receipt(self.root, self.first, self.receipt)

    def test_refuse_symlink_input(self):
        (self.first / "balm.jar").unlink()
        (self.first / "balm.jar").symlink_to(self.first / "waystones.jar")
        with self.assertRaises(CASRejected):
            import_receipt(self.root, self.first, self.receipt)

    def test_refuse_symlink_blob(self):
        import_receipt(self.root, self.first, self.receipt)
        sha = self.receipt["staged_jars"][0]["sha256"]
        blob = self.root / ".totemops-cas" / "objects" / "sha256" / sha[:2] / sha
        blob.unlink()
        blob.symlink_to(self.first / "balm.jar")
        with self.assertRaisesRegex(CASRejected, "cas_blob_symlink"):
            restore_receipt(self.root, self.root / "dest", self.receipt)

    def test_refuse_symlinked_cas_parent_folder(self):
        # An attacker must not redirect the CAS object store outside sandbox.
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / ".totemops-cas").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(CASRejected, "cas_parent_symlink"):
            import_receipt(self.root, self.first, self.receipt)
        self.assertEqual(list(outside.iterdir()), [])

    def test_refuse_symlinked_cas_objects_folder(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        cache = self.root / ".totemops-cas"
        cache.mkdir()
        (cache / "objects").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(CASRejected, "cas_parent_symlink"):
            import_receipt(self.root, self.first, self.receipt)

    def test_refuse_unmarked_directory(self):
        (self.root / ".agy-manager-sandbox").unlink()
        with self.assertRaisesRegex(CASRejected, "sandbox_marker_invalid"):
            import_receipt(self.root, self.first, self.receipt)

    def test_refuse_nonempty_restore(self):
        import_receipt(self.root, self.first, self.receipt)
        out = self.root / "world"
        out.mkdir()
        with self.assertRaisesRegex(CASRejected, "protected_path"):
            restore_receipt(self.root, out, self.receipt)

    def test_fail_closed_on_hash_mismatch_before_manifest(self):
        self.receipt["staged_jars"][1]["sha256"] = "f" * 64
        with self.assertRaisesRegex(CASRejected, "source_sha256_mismatch"):
            import_receipt(self.root, self.first, self.receipt)
        self.assertEqual(stats(self.root)["manifests"], 0)


if __name__ == "__main__":
    unittest.main()
