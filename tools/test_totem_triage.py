# SPDX-License-Identifier: Apache-2.0
"""Unit tests for TotemOps triage verdict engine."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mc_operator import main as mc_operator_main
from totem_triage import format_human_triage, run_triage, main as triage_main

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


class TotemTriageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _make_jar(self, name: str, toml_content: str, toml_name: str = "META-INF/mods.toml") -> Path:
        p = self.root / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(toml_name, toml_content)
        return p

    def _make_mrpack(self, name: str, index_obj: dict | None, override_jars: dict[str, str] | None = None) -> Path:
        p = self.root / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            if index_obj is not None:
                z.writestr("modrinth.index.json", json.dumps(index_obj))
            if override_jars:
                for jar_name, toml_content in override_jars.items():
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as jz:
                        jz.writestr("META-INF/mods.toml", toml_content)
                    z.writestr(f"overrides/mods/{jar_name}", buf.getvalue())
        return p

    def _write_log(self, text: str, name: str = "latest.log") -> Path:
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_01_missing_deps_no_log(self):
        """1. triage: missing dependency + no log -> REVIEW_REQUIRED, exit 3, fixplan_summary is None, actions has details."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        res = run_triage(self.root)
        self.assertEqual(res["verdict"], "REVIEW_REQUIRED")
        self.assertIsNone(res["fixplan_summary"])
        self.assertGreaterEqual(len(res["actions"]), 1)
        action_text = res["actions"][0]["action"]
        self.assertIn("balm", action_text)
        self.assertIn("[21.1,)", action_text)
        self.assertTrue(res["actions"][0]["blocks_boot"])
        self.assertEqual(res["closure_summary"]["missing"], 1)
        self.assertIsNone(res["reason"])

        # CLI execution
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root), "--json"])
        self.assertEqual(code, 3)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["verdict"], "REVIEW_REQUIRED")
        self.assertIsNone(loaded["fixplan_summary"])

    def test_02_all_deps_satisfied_no_log(self):
        """2. triage: all dependencies satisfied + no log -> PASS, exit 0, next_step mentions sandbox."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_21)
        res = run_triage(self.root)
        self.assertEqual(res["verdict"], "PASS")
        self.assertIsNone(res["fixplan_summary"])
        self.assertEqual(res["actions"], [])
        self.assertIn("沙盒實跑", res["next_step"])
        self.assertIsNone(res["reason"])

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root), "--json"])
        self.assertEqual(code, 0)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["verdict"], "PASS")

    def test_03_closure_pass_but_log_has_missing_class(self):
        """3. triage: closure PASS but log has missing_class -> verdict REVIEW_REQUIRED, exit 3 (NOT overwritten by PASS)."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_21)
        log = self._write_log("[12:00:00] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n")

        res = run_triage(self.root, log_path=log)
        self.assertEqual(res["closure_summary"]["status"], "PASS")
        self.assertIsNotNone(res["fixplan_summary"])
        self.assertEqual(res["fixplan_summary"]["status"], "PLAN_ONLY")
        self.assertIn("missing_class", res["fixplan_summary"]["signals"])
        self.assertEqual(res["verdict"], "REVIEW_REQUIRED")
        self.assertGreater(len(res["conflicts"]), 0)

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root), "--log", str(log), "--json"])
        self.assertEqual(code, 3)
        loaded = json.loads(out.getvalue())
        self.assertEqual(loaded["verdict"], "REVIEW_REQUIRED")

    def test_04_log_path_not_found(self):
        """4. triage: log path nonexistent -> BLOCK, exit 2, reason clear; does not output log content."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_21)
        nonexistent_log = self.root / "does_not_exist.log"
        res = run_triage(self.root, log_path=nonexistent_log)
        self.assertEqual(res["verdict"], "BLOCK")
        self.assertEqual(res["reason"], "log_path_not_found")

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root), "--log", str(nonexistent_log), "--json"])
        self.assertEqual(code, 2)
        raw_out = out.getvalue()
        self.assertNotIn("does_not_exist", raw_out)
        loaded = json.loads(raw_out)
        self.assertEqual(loaded["verdict"], "BLOCK")
        self.assertEqual(loaded["reason"], "log_path_not_found")

    def test_05_privacy_no_absolute_paths(self):
        """5. triage: output does not contain absolute paths (tempdir string must not appear)."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        log = self._write_log("[12:00:00] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n")

        res = run_triage(self.root, log_path=log)
        json_str = json.dumps(res, sort_keys=True)
        self.assertNotIn(str(self.root), json_str)
        self.assertNotIn(str(self.temp_dir.name), json_str)

        human_str = format_human_triage(res)
        self.assertNotIn(str(self.root), human_str)
        self.assertNotIn(str(self.temp_dir.name), human_str)

    def test_06_json_vs_human_mode(self):
        """6. triage: --json is single json.loads object; human mode is <= 12 lines and not JSON."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)

        # JSON mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root), "--json"])
        self.assertEqual(code, 3)
        raw_json = out.getvalue().strip()
        data = json.loads(raw_json)
        self.assertIsInstance(data, dict)
        self.assertEqual(data["schema"], "totemops.triage/1")

        # Human mode
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(self.root)])
        self.assertEqual(code, 3)
        human_text = out.getvalue().strip()
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human_text)
        self.assertTrue(human_text.startswith("【TotemOps 裁決】"))
        lines = human_text.splitlines()
        self.assertLessEqual(len(lines), 12)
        self.assertTrue(lines[-1].startswith("下一步："))

    def test_07_mrpack_input_triage(self):
        """7. triage: .mrpack with overrides vs without overrides."""
        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": "1.0.0",
            "name": "TestPack",
            "files": [{"path": "mods/remote.jar"}],
        }
        # Overrides with waystones + balm
        pack_ok = self._make_mrpack("ok.mrpack", index, {
            "waystones.jar": FORGE_WAYSTONES,
            "balm.jar": FORGE_BALM_21,
        })
        res_ok = run_triage(pack_ok)
        self.assertEqual(res_ok["verdict"], "PASS")
        self.assertEqual(res_ok["inputs"][0]["kind"], "mrpack")

        # No overrides -> BLOCK
        pack_empty = self._make_mrpack("empty.mrpack", index)
        res_empty = run_triage(pack_empty)
        self.assertEqual(res_empty["verdict"], "BLOCK")
        self.assertEqual(res_empty["reason"], "mrpack_contains_no_local_jars")

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = mc_operator_main(["triage", str(pack_empty), "--json"])
        self.assertEqual(code, 2)

    def test_08_action_ranking_order(self):
        """8. triage: action ranking orders blocks_boot=True first, then closure before fixplan, then sorted by name."""
        # Waystones missing balm
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        # Log with missing_class
        log = self._write_log("[12:00:00] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n")
        res = run_triage(self.root, log_path=log)

        actions = res["actions"]
        self.assertGreaterEqual(len(actions), 2)
        # First action should be closure missing balm
        self.assertEqual(actions[0]["source"], "closure")
        self.assertEqual(actions[0]["rank"], 1)
        self.assertTrue(actions[0]["blocks_boot"])
        # Second action should be fixplan
        self.assertEqual(actions[1]["source"], "fixplan")
        self.assertEqual(actions[1]["rank"], 2)
        self.assertTrue(actions[1]["blocks_boot"])

    def test_09_standalone_triage_main(self):
        """9. triage: totem_triage.py standalone main() invocation."""
        self._make_jar("waystones.jar", FORGE_WAYSTONES)
        self._make_jar("balm.jar", FORGE_BALM_21)

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = triage_main([str(self.root), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["verdict"], "PASS")

        with patch("sys.stdout", new_callable=StringIO) as out:
            code = triage_main([str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("【TotemOps 裁決】", out.getvalue())


if __name__ == "__main__":
    unittest.main()
