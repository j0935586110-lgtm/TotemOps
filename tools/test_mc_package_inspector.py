# SPDX-License-Identifier: Apache-2.0
"""Read-only fixtures for Minecraft JAR, packs, declared dependencies and logs."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mc_package_inspector import InputBlocked, inspect_log, inspect_one, inspect_path

FORGE = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="foo"
version="1.0"
displayName="Foo"
[[dependencies.foo]]
modId="bar"
mandatory=true
versionRange="[2,)"
side="BOTH"
[[dependencies.foo]]
modId="minecraft"
mandatory=true
versionRange="[1.20.1,)"
"""

NEOFORGE = """
modLoader="javafml"
loaderVersion="[2,)"
license="MIT"
[[mods]]
modId="neo"
version="0.2.0"
[[dependencies.neo]]
modId="foo"
type="incompatible"
versionRange="[1,)"
"""

class PackageInspectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def makezip(self, name, members):
        p = self.root / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for member, data in members.items():
                z.writestr(member, data)
        return p

    def test_forge_toml_required_and_builtin(self):
        path = self.makezip("foo.jar", {"META-INF/mods.toml": FORGE})
        result = inspect_path(path)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["packages"][0]["mods"][0]["id"], "foo")
        self.assertEqual(len(result["packages"][0]["dependencies"]), 2)
        self.assertEqual([x["target"] for x in result["findings"]], ["bar"])
        self.assertEqual(result["findings"][0]["severity"], "review")
        self.assertIn("Maven_range_solver", result["checks_not_run"])

    def test_neoforge_incompatible_present(self):
        self.makezip("foo.jar", {"META-INF/mods.toml": FORGE})
        self.makezip("neo.jar", {"META-INF/neoforge.mods.toml": NEOFORGE})
        result = inspect_path(self.root)
        self.assertTrue(any(x["kind"] == "declared_incompatible" for x in result["findings"]))
        self.assertFalse(any(x["kind"] == "required_not_in_supplied_set" and x["target"] == "foo" for x in result["findings"]))

    def test_duplicates_are_conflicts(self):
        self.makezip("a.jar", {"META-INF/mods.toml": FORGE})
        self.makezip("b.jar", {"META-INF/mods.toml": FORGE})
        result = inspect_path(self.root)
        self.assertTrue(any(x["kind"] == "duplicate_mod_id" for x in result["findings"]))

    def test_fabric_json(self):
        self.makezip("fabric.jar", {"fabric.mod.json": json.dumps({
            "id": "fabricmod", "version": "2.0", "depends": {"fabricloader": ">=0.15", "lib": "*"},
            "breaks": {"badmod": "*"}
        })})
        result = inspect_path(self.root)
        self.assertEqual(result["packages"][0]["mods"][0]["loader"], "fabric")
        self.assertTrue(any(f["target"] == "lib" for f in result["findings"]))

    def test_paper_plugin_yaml(self):
        self.makezip("plugin.jar", {"paper-plugin.yml": (
            "name: MyPlugin\nversion: 1.2.0\ndependencies:\n  server:\n"
            "    Vault:\n      required: true\n      load: BEFORE\n"
        )})
        result = inspect_path(self.root)
        self.assertEqual(result["packages"][0]["mods"][0]["loader"], "paper")
        self.assertEqual(result["findings"][0]["target"], "Vault")

    def test_bukkit_plugin_yaml(self):
        self.makezip("plugin.jar", {"plugin.yml": "name: BukkitFun\nversion: 1\ndepend: [Vault]\nsoftdepend: [WorldEdit]\n"})
        result = inspect_path(self.root)
        self.assertEqual(len(result["packages"][0]["dependencies"]), 2)
        self.assertEqual(result["findings"][0]["target"], "Vault")

    def test_mrpack_metadata(self):
        manifest = {
            "formatVersion": 1, "name": "FriendsPack", "versionId": "0.1",
            "dependencies": {"minecraft": "1.21.1", "neoforge": "21.1.1"},
            "files": [{"path": "mods/alpha.jar", "hashes": {"sha512": "abc"},
                       "downloads": ["https://example.test/a"], "env": {"server": "required"}}],
        }
        p = self.makezip("pack.mrpack", {"modrinth.index.json": json.dumps(manifest)})
        r = inspect_one(p)
        self.assertEqual(r["pack"]["name"], "FriendsPack")
        self.assertEqual(r["pack"]["files_count"], 1)
        self.assertEqual(r["pack"]["loader_versions"]["minecraft"], "1.21.1")

    def test_corrupt_zip_blocked(self):
        p = self.root / "bad.jar"
        p.write_bytes(b"NO ZIP")
        result = inspect_path(p)
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["files_rejected"][0]["reason"], "invalid_archive_or_metadata")

    def test_invalid_toml_rejected(self):
        p = self.makezip("bad.jar", {"META-INF/mods.toml": "[[mods]\n"})
        self.assertEqual(inspect_path(p)["status"], "BLOCK")

    def test_unknown_metadata_does_not_invent(self):
        p = self.makezip("unknown.jar", {"random.txt": "hello"})
        r = inspect_one(p)
        self.assertEqual(r["mods"], [])
        self.assertEqual(r["maintenance"]["status"], "UNKNOWN")
        self.assertIn("no_supported_metadata", r["warnings"])

    def test_symlink_block(self):
        p = self.makezip("real.jar", {"META-INF/mods.toml": FORGE})
        target = self.root / "link.jar"
        target.symlink_to(p)
        with self.assertRaises(InputBlocked):
            inspect_one(target)

    def test_metadata_zip_bomb_block(self):
        p = self.makezip("large.jar", {"META-INF/mods.toml": "A" * (1024 * 1024 + 1)})
        self.assertEqual(inspect_path(p)["status"], "BLOCK")

    def test_filename_metadata_version_mismatch_flagged_not_auto_fixed(self):
        p = self.makezip("foo-1.0.2.jar", {"META-INF/mods.toml": FORGE})
        result = inspect_path(p)
        self.assertEqual(result["status"], "PASS")
        issues = [x for x in result["findings"] if x["kind"] == "filename_metadata_version_mismatch_candidate"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["declared_version"], "1.0")
        self.assertEqual(issues[0]["severity"], "review")
        self.assertEqual(len(result["packages"][0]["hashes"]["sha512"]), 128)

    def test_cross_loader_requires_target_not_assumed_compatible(self):
        self.makezip("foo.jar", {"META-INF/mods.toml": FORGE})
        self.makezip("neo.jar", {"META-INF/neoforge.mods.toml": NEOFORGE})
        result = inspect_path(self.root)
        issues = [x for x in result["findings"] if x["kind"] == "mixed_mod_loaders"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "review")

    def test_mrpack_unsafe_paths_block(self):
        manifest = {"formatVersion": 1, "files": [{"path": "../world/level.dat"}]}
        p = self.makezip("evil.mrpack", {"modrinth.index.json": json.dumps(manifest)})
        self.assertEqual(inspect_path(p)["status"], "BLOCK")

    def test_untrusted_yaml_tag_blocked(self):
        p = self.makezip("evil.jar", {"plugin.yml": "!!python/object/apply:os.system ['echo bad']"})
        self.assertEqual(inspect_path(p)["status"], "BLOCK")

    def test_no_supported_packages(self):
        with self.assertRaises(InputBlocked):
            inspect_path(self.root)

    def test_log_out_of_memory_not_attributed_to_mod(self):
        log = self.root / "latest.log"
        log.write_text("Error java.lang.OutOfMemoryError: Java heap space\n")
        r = inspect_log(log)
        self.assertEqual(r["signals"][0]["kind"], "out_of_memory")
        self.assertIsNone(r["confirmed_faulty_mod"])

    def test_client_only_class_mentioned_on_server_is_clue(self):
        p = self.root / "invalid-dist.log"
        p.write_text("Caused by: java.lang.NoClassDefFoundError: net/minecraft/client/Minecraft\n")
        result = inspect_log(p)
        self.assertEqual(result["signals"][0]["kind"], "client_class_on_server")
        self.assertIsNone(result["confirmed_faulty_mod"])

    def test_explicit_invalid_dedicated_server_dist_is_clue(self):
        p = self.root / "dist.log"
        p.write_text("Attempted to load class net/minecraft/client/gui/Screen for invalid dist DEDICATED_SERVER\n")
        result = inspect_log(p)
        self.assertEqual(result["signals"][0]["kind"], "invalid_dedicated_server_dist")
        self.assertIsNone(result["confirmed_faulty_mod"])

    def test_log_missing_class_clue(self):
        log = self.root / "latest.log"
        log.write_text("Caused by: java.lang.NoClassDefFoundError: com/sample/SomeClass\n")
        r = inspect_log(log)
        self.assertEqual(r["signals"][0]["kind"], "missing_class")
        self.assertEqual(r["signals"][0]["assessment"], "clue_not_confirmed_root_cause")


if __name__ == "__main__":
    unittest.main()
