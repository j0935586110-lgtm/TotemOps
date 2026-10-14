# SPDX-License-Identifier: Apache-2.0
"""Tiny local cache selection tests: verify, copy, reject, never hardlink."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from totem_local_cache import clone_if_faster, discover_verified_cache, LocalCacheRejected


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "agy-sandbox"
        self.root.mkdir()
        self.source = self.root / "old-run" / "mods"
        self.source.mkdir(parents=True)
        self.payload = b"jar fixture data, not executable"
        self.jar = self.source / "a.jar"
        self.jar.write_bytes(self.payload)
        self.want = {"a.jar": hashlib.sha256(self.payload).hexdigest()}
        self.dest = self.root / "new-run" / "mods"

    def test_bounded_auto_discovery(self):
        self.assertEqual(discover_verified_cache(self.root, self.want), self.source)

    def test_faster_cache_independent_copy(self):
        x = clone_if_faster(self.source, self.root, self.dest, self.want, 15.0)
        self.assertEqual(x["decision"], "LOCAL_COPY")
        self.assertEqual((self.dest / "a.jar").read_bytes(), self.payload)
        self.assertNotEqual((self.jar).stat().st_ino, (self.dest / "a.jar").stat().st_ino)

    def test_historical_download_is_faster(self):
        x = clone_if_faster(self.source, self.root, self.dest, self.want, .001)
        self.assertEqual(x["decision"], "DOWNLOAD")
        self.assertFalse(self.dest.exists())

    def test_invalid_hash_blocks_copy(self):
        with self.assertRaisesRegex(LocalCacheRejected, "hash_mismatch"):
            clone_if_faster(self.source, self.root, self.dest,
                            {"a.jar": "0" * 64}, 15.0)
        self.assertFalse(self.dest.exists())

    def test_outside_dir_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "a.jar").write_bytes(self.payload)
        with self.assertRaisesRegex(LocalCacheRejected, "outside"):
            clone_if_faster(outside, self.root, self.dest, self.want, 15)

    def test_protected_world_rejected(self):
        folder = self.root / "world" / "mods"
        folder.mkdir(parents=True)
        (folder / "a.jar").write_bytes(self.payload)
        with self.assertRaisesRegex(LocalCacheRejected, "protected"):
            clone_if_faster(folder, self.root, self.dest, self.want, 15)

    def test_symlink_rejected(self):
        alias = self.root / "linked"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(LocalCacheRejected, "not_regular"):
            clone_if_faster(alias, self.root, self.dest, self.want, 15.0)

    def test_missing_file_falls_back(self):
        x = clone_if_faster(self.source, self.root, self.dest,
                            {**self.want, "missing.jar": "1" * 64}, 15)
        self.assertEqual(x["decision"], "DOWNLOAD")


if __name__ == "__main__":
    unittest.main()
