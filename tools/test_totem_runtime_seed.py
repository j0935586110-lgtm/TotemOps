# SPDX-License-Identifier: Apache-2.0
"""Version-pinned NeoForge loader seed tests; world/private files never copied."""
import json
import tempfile
import unittest
from pathlib import Path

from totem_runtime_seed import create_seed, prepare_seed, SeedRejected, SEED_JSON


class RuntimeSeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"agy-sandbox"
        self.root.mkdir()
        self.src=self.root/"runtime-base"/"data"
        self.src.mkdir(parents=True)
        self.lib=self.src/"libraries/net/neoforged/neoforge/21.1.259"
        self.lib.mkdir(parents=True)
        (self.lib/"unix_args.txt").write_text("--help")
        (self.src/"run.sh").write_text('java @libraries/net/neoforged/neoforge/21.1.259/unix_args.txt\n')
        (self.src/".neoforge-manifest.json").write_text(json.dumps({
            "minecraftVersion":"1.21.1", "forgeVersion":"21.1.259", "serverEntry":"run.sh"}))
        (self.src/"world").mkdir()
        (self.src/"world"/"level.dat").write_bytes(b"private world")
        (self.src/"config").mkdir()
        (self.src/"config"/"private.secret").write_bytes(b"private")
        self.seed=self.root/"seed-nf"
        self.out=self.root/"clone"/"data"
        self.image="sha256:"+"f"*64

    def create(self):
        return create_seed(self.src,self.seed,self.root,"1.21.1","21.1.259",self.image)

    def test_cli_create_seed_with_explicit_local_image_id(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from totem_operator import main
        (self.root / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["runtime-seed","create","--source",str(self.src),
                         "--sandbox-root",str(self.root),
                         "--seed-dir",str(self.seed),
                         "--game-version","1.21.1",
                         "--loader-version","21.1.259",
                         "--image-id",self.image])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out.getvalue())["status"],"SEED_CREATED")
        self.assertFalse((self.seed/"world").exists())

    def test_seed_allowlist_excludes_world_and_custom_config(self):
        result=self.create()
        self.assertEqual(result["status"],"SEED_CREATED")
        self.assertFalse((self.seed/"world").exists())
        self.assertFalse((self.seed/"config").exists())
        meta=json.loads((self.seed/SEED_JSON).read_text())
        self.assertEqual(meta["loader_version"],"21.1.259")

    def test_independent_copy_matches_source_and_not_hardlink(self):
        self.create()
        result=prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.259",self.image,100)
        self.assertEqual(result["status"],"LOCAL_LOADER_CLONE")
        self.assertEqual((self.out/"run.sh").read_text(),(self.src/"run.sh").read_text())
        self.assertNotEqual((self.out/"run.sh").stat().st_ino,(self.seed/"run.sh").stat().st_ino)
        self.assertFalse((self.out/"world").exists())
        self.assertFalse((self.out/"config").exists())

    def test_loader_version_mismatch_chooses_download(self):
        self.create()
        x=prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.260",self.image,100)
        self.assertEqual(x["status"],"DOWNLOAD")
        self.assertFalse(self.out.exists())

    def test_image_mismatch_chooses_download(self):
        self.create()
        x=prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.259","sha256:"+"0"*64,100)
        self.assertEqual(x["status"],"DOWNLOAD")

    def test_if_download_measured_faster_use_it(self):
        self.create()
        x=prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.259",self.image,.0001)
        self.assertEqual(x["status"],"DOWNLOAD")

    def test_mutated_cache_blocked(self):
        self.create()
        (self.seed/"run.sh").write_text("changed")
        with self.assertRaisesRegex(SeedRejected,"seed_hash_mismatch"):
            prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.259",self.image,100)

    def test_create_requires_real_matching_neoforge_runtime(self):
        with self.assertRaises(SeedRejected):
            create_seed(self.src,self.seed,self.root,"1.21.1","21.1.260",self.image)

    def test_refuses_existing_target(self):
        self.create()
        with self.assertRaisesRegex(SeedRejected,"already_exists"):
            self.create()

    def test_target_cannot_be_within_world(self):
        with self.assertRaisesRegex(SeedRejected,"protected_path"):
            create_seed(self.src,self.root/"world"/"seed",self.root,"1.21.1","21.1.259",self.image)

    def test_refuses_nonempty_clone_folder(self):
        self.create()
        self.out.mkdir(parents=True)
        (self.out/"world").mkdir()
        with self.assertRaisesRegex(SeedRejected,"must_be_empty"):
            prepare_seed(self.seed,self.out,self.root,"1.21.1","21.1.259",self.image,100)


if __name__=="__main__":
    unittest.main()
