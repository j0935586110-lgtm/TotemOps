# SPDX-License-Identifier: Apache-2.0
"""Unit tests for TotemOps dependency closure verifier."""
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
from totem_dependency_closure import check_closure, evaluate_version_range, format_human_closure

FORGE_WAYSTONES = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="waystones"
version="21.1.0"
displayName="Waystones"
[[dependencies.waystones]]
modId="balm"
mandatory=true
versionRange="[21.1,)"
side="BOTH"
[[dependencies.waystones]]
modId="minecraft"
mandatory=true
versionRange="[1.21.1,)"
"""

FORGE_BALM_21 = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="balm"
version="21.1.0"
displayName="Balm"
"""

FORGE_BALM_3 = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="balm"
version="3.0"
displayName="Balm"
"""

FORGE_BALM_UNKNOWN = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="balm"
displayName="Balm"
"""

FORGE_BALM_BETA = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="balm"
version="21.1.259-beta"
displayName="Balm"
"""

NEO_SERVER_ONLY = """
modLoader="javafml"
loaderVersion="[2,)"
license="MIT"
[[mods]]
modId="serveronly"
version="1.0"
[[dependencies.serveronly]]
modId="spark"
mandatory=true
versionRange="*"
side="SERVER"
"""

NEO_INCOMPAT = """
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
[[dependencies.neo]]
modId="optmod"
type="optional"
versionRange="*"
"""

FOO_MOD = """
modLoader="javafml"
loaderVersion="[47,)"
license="MIT"
[[mods]]
modId="foo"
version="1.0"
"""


class TotemClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _make_jar(self, name: str, toml_content: str, folder: Path | None = None, toml_name: str = "META-INF/mods.toml") -> Path:
        base = folder or self.root
        p = base / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(toml_name, toml_content)
        return p

    def test_01_single_jar_missing_required(self):
        """1. closure: single jar missing required dep -> missing 1 item, required_by correct, exit 3."""
        jar = self._make_jar("waystones.jar", FORGE_WAYSTONES)
        res = check_closure(jar)
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(res["missing"]), 1)
        self.assertEqual(res["missing"][0]["to"], "balm")
        self.assertEqual(res["missing"][0]["required_by"], ["waystones"])
        self.assertEqual(res["missing"][0]["version_ranges"], ["[21.1,)"])
        self.assertEqual(res["missing"][0]["side"], "BOTH")
        self.assertEqual(res["missing"][0]["reason"], "not_in_supplied_set")

        # Test CLI exit code 3
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(jar), "--json"])
        self.assertEqual(code, 3)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(loaded["missing"]), 1)

    def test_02_dependencies_complete_pass(self):
        """2. closure: dependencies complete and version satisfied -> PASS, exit 0."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_21)
        res = check_closure(self.root)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["version_mismatch"], [])
        self.assertEqual(res["incompatible_pairs"], [])
        self.assertEqual(res["unresolved_ranges"], [])
        self.assertEqual(res["supplied"]["count"], 2)

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(self.root), "--json"])
        self.assertEqual(code, 0)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["status"], "PASS")

    def test_03_version_mismatch(self):
        """3. closure: version not satisfied (req [4,) but sup 3.0) -> version_mismatch, exit 3."""
        # Waystones requires [4,) from balm
        req_toml = """
modLoader="javafml"
[[mods]]
modId="waystones"
version="1.0"
[[dependencies.waystones]]
modId="balm"
mandatory=true
versionRange="[4,)"
side="BOTH"
"""
        self._make_jar("waystones.jar", req_toml)
        self._make_jar("balm.jar", FORGE_BALM_3)
        res = check_closure(self.root)
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(res["version_mismatch"]), 1)
        vm = res["version_mismatch"][0]
        self.assertEqual(vm["to"], "balm")
        self.assertEqual(vm["supplied_version"], "3.0")
        self.assertEqual(vm["required_by"], ["waystones"])
        self.assertEqual(vm["version_range"], "[4,)")
        self.assertEqual(vm["reason"], "declared_range_not_satisfied")

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(self.root), "--json"])
        self.assertEqual(code, 3)

    def test_04_side_filtering(self):
        """4. closure: side filter (SERVER edge ignored under --side client)."""
        self._make_jar("serveronly.jar", NEO_SERVER_ONLY)
        # Under --side server or --side both, spark is missing
        res_server = check_closure(self.root, side="server")
        self.assertEqual(res_server["status"], "REVIEW_REQUIRED")
        self.assertTrue(any(m["to"] == "spark" for m in res_server["missing"]))

        # Under --side client, spark is ignored because it's a SERVER edge
        res_client = check_closure(self.root, side="client")
        self.assertEqual(res_client["status"], "PASS")
        self.assertEqual(res_client["missing"], [])

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(self.root), "--side", "client", "--json"])
        self.assertEqual(code, 0)

    def test_05_incompatible_pairs_and_optional(self):
        """5. closure: incompatible pairs detected; optional edge does not count as missing."""
        self._make_jar("neo.jar", NEO_INCOMPAT, toml_name="META-INF/neoforge.mods.toml")
        self._make_jar("foo.jar", FOO_MOD)
        res = check_closure(self.root)
        self.assertEqual(res["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(res["incompatible_pairs"]), 1)
        self.assertEqual(res["incompatible_pairs"][0]["from"], "neo")
        self.assertEqual(res["incompatible_pairs"][0]["to"], "foo")
        # optmod is optional, so it is NOT missing
        self.assertFalse(any(m["to"] == "optmod" for m in res["missing"]))

    def test_06_unresolved_ranges_not_satisfied(self):
        """6. closure: unresolvable ranges (~1.2, 1.20.x-beta, supplied=UNKNOWN) -> unresolved_ranges, never PASS."""
        # Subtest A: ~1.2
        res, reason, _ = evaluate_version_range("1.2.0", "~1.2")
        self.assertEqual(res, "UNRESOLVED")

        # Subtest B: 1.20.x-beta
        res, reason, _ = evaluate_version_range("1.20.1", "1.20.x-beta")
        self.assertEqual(res, "UNRESOLVED")

        # Subtest C: supplied UNKNOWN
        res, reason, _ = evaluate_version_range("UNKNOWN", "[21.1,)")
        self.assertEqual(res, "UNRESOLVED")
        self.assertEqual(reason, "supplied_version_unknown")

        # Subtest D: supplied version with non-numeric suffix
        res, reason, note = evaluate_version_range("21.1.259-beta", "[21.1,)")
        self.assertEqual(res, "UNRESOLVED")
        self.assertEqual(reason, "non_numeric_version_suffix")
        self.assertIn("-beta", note)

        # Integration: jar requiring balm, supplied balm is UNKNOWN
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_UNKNOWN)
        closure_res = check_closure(self.root)
        self.assertEqual(closure_res["status"], "REVIEW_REQUIRED")
        self.assertTrue(any(u["to"] == "balm" for u in closure_res["unresolved_ranges"]))
        self.assertEqual(closure_res["unresolved_ranges"][0]["reason"], "supplied_version_unknown")

    def test_07_nonexistent_or_empty_block_and_privacy(self):
        """7. closure: nonexistent path / empty folder -> BLOCK exit 2; output has no absolute path."""
        empty_dir = self.root / "empty"
        empty_dir.mkdir()
        res_empty = check_closure(empty_dir)
        self.assertEqual(res_empty["status"], "BLOCK")
        self.assertNotIn(str(self.root), json.dumps(res_empty))

        nonexistent = self.root / "does_not_exist"
        res_nonexistent = check_closure(nonexistent)
        self.assertEqual(res_nonexistent["status"], "BLOCK")
        self.assertNotIn(str(self.root), json.dumps(res_nonexistent))

        # Check CLI exit code 2
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(nonexistent), "--json"])
        self.assertEqual(code, 2)
        out_str = out.getvalue()
        self.assertNotIn(str(self.root), out_str)

    def test_08_multiple_mods_requiring_same_missing(self):
        """Missing target mod required by multiple mods is merged with deduplicated required_by."""
        mod1 = """
modLoader="javafml"
[[mods]]
modId="mod1"
version="1.0"
[[dependencies.mod1]]
modId="common_lib"
mandatory=true
versionRange="[1.0,)"
side="BOTH"
"""
        mod2 = """
modLoader="javafml"
[[mods]]
modId="mod2"
version="1.0"
[[dependencies.mod2]]
modId="common_lib"
mandatory=true
versionRange="[1.5,)"
side="SERVER"
"""
        self._make_jar("mod1.jar", mod1)
        self._make_jar("mod2.jar", mod2)
        res = check_closure(self.root)
        self.assertEqual(len(res["missing"]), 1)
        m = res["missing"][0]
        self.assertEqual(m["to"], "common_lib")
        self.assertEqual(m["required_by"], ["mod1", "mod2"])
        self.assertEqual(m["version_ranges"], ["[1.0,)", "[1.5,)"])
        self.assertEqual(m["side"], "BOTH")

    def test_09_cli_json_vs_human_mode(self):
        """14. CLI layer: --json emits single json.loads-able object; human mode does not output JSON."""
        jar = self._make_jar("waystones.jar", FORGE_WAYSTONES)

        # JSON mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(jar), "--json"])
        raw = out.getvalue().strip()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["schema"], "totemops.closure/1")

        # Human mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["closure", str(jar)])
        human_text = out.getvalue().strip()
        # Must not be parseable as JSON
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human_text)
        self.assertIn("TotemOps 依賴閉包檢查結果", human_text)
        self.assertIn("balm", human_text)


if __name__ == "__main__":
    unittest.main()
