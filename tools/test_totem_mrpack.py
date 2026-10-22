# SPDX-License-Identifier: Apache-2.0
"""Unit tests for TotemOps Modrinth .mrpack index exporter."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from mc_operator import main as mc_operator_main
from mc_package_inspector import _hashes
from totem_mrpack import build_packindex, format_human_packindex, is_safe_url


class TotemMrpackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mods_dir = self.root / "mods"
        self.mods_dir.mkdir()

    def _make_dummy_jar(self, name: str, content: bytes = b"dummy jar content") -> Path:
        p = self.mods_dir / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("test.txt", content)
        return p

    def _make_map(self, mapping: dict) -> Path:
        p = self.root / "downloads.json"
        p.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        return p

    def test_08_no_map_plan_only(self):
        """8. packindex: no map -> PLAN_ONLY, exit 3, unresolved lists all files, no file written."""
        self._make_dummy_jar("a.jar")
        self._make_dummy_jar("b.jar")

        res = build_packindex(
            mods_dir=self.mods_dir,
            name="TestPack",
            version="1.0.0",
            minecraft="1.21.1",
            loader="neoforge",
        )
        self.assertEqual(res["status"], "PLAN_ONLY")
        self.assertEqual(res["total_jars"], 2)
        self.assertEqual(res["resolved_count"], 0)
        self.assertEqual(res["unresolved_count"], 2)
        self.assertEqual(res["unresolved"], ["a.jar", "b.jar"])
        self.assertIn("index", res)
        self.assertEqual(res["index"]["files"], [])

        # Check CLI invocation: exit code 3
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main([
                "packindex", str(self.mods_dir),
                "--name", "TestPack",
                "--version", "1.0.0",
                "--minecraft", "1.21.1",
                "--loader", "neoforge",
                "--json",
            ])
        self.assertEqual(code, 3)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["status"], "PLAN_ONLY")
        self.assertEqual(loaded["unresolved"], ["a.jar", "b.jar"])

    def test_09_complete_map_writes_mrpack_and_verifies(self):
        """9. packindex: complete map -> writes .mrpack, exit 0, zip index sha512/fileSize/path match."""
        jar_a = self._make_dummy_jar("a.jar", b"content_a_12345")
        jar_b = self._make_dummy_jar("b.jar", b"content_b_67890")

        map_path = self._make_map({
            "a.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/a.jar"},
            "b.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/b.jar"},
        })
        out_pack = self.root / "test.mrpack"

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main([
                "packindex", str(self.mods_dir),
                "--name", "TestPack",
                "--version", "1.0.0",
                "--minecraft", "1.21.1",
                "--loader", "neoforge",
                "--downloads-map", str(map_path),
                "--out", str(out_pack),
                "--json",
            ])
        self.assertEqual(code, 0)
        self.assertTrue(out_pack.exists())

        loaded_json = json.loads(out.getvalue())
        self.assertEqual(loaded_json["status"], "PASS")
        self.assertEqual(loaded_json["out"], "test.mrpack")

        # Read back zip and verify sha512, fileSize, path
        with zipfile.ZipFile(out_pack, "r") as z:
            self.assertIn("modrinth.index.json", z.namelist())
            index_data = json.loads(z.read("modrinth.index.json").decode("utf-8"))

        self.assertEqual(index_data["formatVersion"], 1)
        self.assertEqual(index_data["name"], "TestPack")
        self.assertEqual(index_data["versionId"], "1.0.0")
        self.assertEqual(len(index_data["files"]), 2)

        file_a = index_data["files"][0]
        self.assertEqual(file_a["path"], "mods/a.jar")
        self.assertEqual(file_a["fileSize"], jar_a.stat().st_size)
        self.assertEqual(file_a["hashes"]["sha512"], _hashes(jar_a)["sha512"])
        self.assertEqual(file_a["hashes"]["sha1"], _hashes(jar_a)["sha1"])

        file_b = index_data["files"][1]
        self.assertEqual(file_b["path"], "mods/b.jar")
        self.assertEqual(file_b["fileSize"], jar_b.stat().st_size)
        self.assertEqual(file_b["hashes"]["sha512"], _hashes(jar_b)["sha512"])

    def test_10_partial_map_with_out_blocks(self):
        """10. packindex: partial map with --out -> BLOCK downloads_unresolved, exit 2, file not created."""
        self._make_dummy_jar("a.jar")
        self._make_dummy_jar("b.jar")

        map_path = self._make_map({
            "a.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/a.jar"},
        })
        out_pack = self.root / "blocked.mrpack"

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main([
                "packindex", str(self.mods_dir),
                "--name", "TestPack",
                "--version", "1.0.0",
                "--minecraft", "1.21.1",
                "--loader", "neoforge",
                "--downloads-map", str(map_path),
                "--out", str(out_pack),
                "--json",
            ])
        self.assertEqual(code, 2)
        self.assertFalse(out_pack.exists())
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["status"], "BLOCK")
        self.assertEqual(loaded["reason"], "downloads_unresolved")
        self.assertEqual(loaded["unresolved"], ["b.jar"])

    def test_11_invalid_urls_block(self):
        """11. packindex: invalid URLs (http, localhost, 127.0.0.1, user:pw@host, pure IP) -> BLOCK."""
        invalid_cases = [
            "http://foo.com/a.jar",
            "https://127.0.0.1/a.jar",
            "https://user:pw@host.com/a.jar",
            "https://localhost/a.jar",
            "https://192.168.1.1/a.jar",
            "https://10.0.0.1/a.jar",
            "https://8.8.8.8/a.jar",
            "file:///etc/passwd",
            "ftp://host.com/a.jar",
            "https://host.com/a b.jar",
        ]
        for url in invalid_cases:
            safe, reason = is_safe_url(url)
            self.assertFalse(safe, f"Expected {url} to be rejected, got safe=True")

        self._make_dummy_jar("a.jar")
        map_path = self._make_map({
            "a.jar": {"url": "http://insecure.com/a.jar"},
        })
        res = build_packindex(
            mods_dir=self.mods_dir,
            name="TestPack",
            version="1.0.0",
            minecraft="1.21.1",
            loader="neoforge",
            downloads_map_path=map_path,
        )
        self.assertEqual(res["status"], "BLOCK")
        self.assertTrue("invalid_download_url" in res["reason"])

    def test_12_output_exists_or_symlink_blocks(self):
        """12. packindex: output file exists / output path is symlink -> BLOCK, does not overwrite."""
        self._make_dummy_jar("a.jar")
        map_path = self._make_map({
            "a.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/a.jar"},
        })

        # Existing output file
        out_pack = self.root / "existing.mrpack"
        out_pack.write_text("existing content", encoding="utf-8")
        res = build_packindex(
            mods_dir=self.mods_dir,
            name="TestPack",
            version="1.0.0",
            minecraft="1.21.1",
            loader="neoforge",
            downloads_map_path=map_path,
            out_path=out_pack,
        )
        self.assertEqual(res["status"], "BLOCK")
        self.assertEqual(res["reason"], "output_exists")
        # Ensure it was not overwritten
        self.assertEqual(out_pack.read_text(encoding="utf-8"), "existing content")

        # Symlink output path
        real_target = self.root / "real.mrpack"
        sym_link = self.root / "sym.mrpack"
        try:
            os.symlink(real_target, sym_link)
            res_sym = build_packindex(
                mods_dir=self.mods_dir,
                name="TestPack",
                version="1.0.0",
                minecraft="1.21.1",
                loader="neoforge",
                downloads_map_path=map_path,
                out_path=sym_link,
            )
            self.assertEqual(res_sym["status"], "BLOCK")
            self.assertEqual(res_sym["reason"], "symlink_not_allowed")
        except OSError:
            pass

    def test_13_determinism_same_input_same_index_bytes(self):
        """13. Determinism: running twice on same input produces identical modrinth.index.json bytes."""
        self._make_dummy_jar("x.jar", b"content_x")
        self._make_dummy_jar("y.jar", b"content_y")

        map_path = self._make_map({
            "x.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/x.jar"},
            "y.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/y.jar"},
        })
        out1 = self.root / "out1.mrpack"
        out2 = self.root / "out2.mrpack"

        res1 = build_packindex(
            mods_dir=self.mods_dir,
            name="TestPack",
            version="1.0.0",
            minecraft="1.21.1",
            loader="neoforge",
            downloads_map_path=map_path,
            out_path=out1,
        )
        res2 = build_packindex(
            mods_dir=self.mods_dir,
            name="TestPack",
            version="1.0.0",
            minecraft="1.21.1",
            loader="neoforge",
            downloads_map_path=map_path,
            out_path=out2,
        )
        self.assertEqual(res1["status"], "PASS")
        self.assertEqual(res2["status"], "PASS")

        with zipfile.ZipFile(out1, "r") as z1:
            bytes1 = z1.read("modrinth.index.json")
        with zipfile.ZipFile(out2, "r") as z2:
            bytes2 = z2.read("modrinth.index.json")

        self.assertEqual(bytes1, bytes2)

    def test_14_cli_json_vs_human_mode(self):
        """14. CLI layer: --json emits single json.loads-able object; human mode does not output JSON."""
        self._make_dummy_jar("a.jar")

        # JSON mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main([
                "packindex", str(self.mods_dir),
                "--name", "Pack",
                "--version", "1",
                "--minecraft", "1.21",
                "--loader", "neoforge",
                "--json",
            ])
        raw = out.getvalue().strip()
        parsed = json.loads(raw)
        self.assertEqual(parsed["schema"], "totemops.packindex/1")

        # Human mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main([
                "packindex", str(self.mods_dir),
                "--name", "Pack",
                "--version", "1",
                "--minecraft", "1.21",
                "--loader", "neoforge",
            ])
        human_text = out.getvalue().strip()
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human_text)
        self.assertIn("TotemOps .mrpack 打包索引", human_text)
        self.assertIn("未解析模組清單", human_text)

    def test_15_env_side_filtering(self):
        """packindex env mapping according to --side (both, client, server)."""
        self._make_dummy_jar("a.jar")
        map_path = self._make_map({
            "a.jar": {"url": "https://cdn.modrinth.com/data/xxx/versions/yyy/a.jar"},
        })

        res_both = build_packindex(
            mods_dir=self.mods_dir, name="P", version="1", minecraft="1.21",
            loader="neoforge", downloads_map_path=map_path, side="both"
        )
        self.assertEqual(res_both["index"]["files"][0]["env"], {"client": "required", "server": "required"})

        res_client = build_packindex(
            mods_dir=self.mods_dir, name="P", version="1", minecraft="1.21",
            loader="neoforge", downloads_map_path=map_path, side="client"
        )
        self.assertEqual(res_client["index"]["files"][0]["env"], {"client": "required", "server": "unsupported"})

        res_server = build_packindex(
            mods_dir=self.mods_dir, name="P", version="1", minecraft="1.21",
            loader="neoforge", downloads_map_path=map_path, side="server"
        )
        self.assertEqual(res_server["index"]["files"][0]["env"], {"client": "unsupported", "server": "required"})


if __name__ == "__main__":
    unittest.main()
