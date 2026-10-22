# SPDX-License-Identifier: Apache-2.0
"""Tests for TotemOps deterministic, read-only repair recipe planner (fixplan)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mc_package_inspector import PATTERNS
from mc_operator import main as mc_operator_main
from totem_repair_recipes import (
    DEFAULT_CATALOG_PATH,
    build_fixplan,
    format_human_plan,
    load_catalog,
    main as repair_main,
)


class TotemFixplanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _write_log(self, text: str, name: str | None = None) -> Path:
        fname = name or f"test_{self._testMethodName}.log"
        p = self.root / fname
        p.write_text(text, encoding="utf-8")
        return p

    def test_01_out_of_memory_plan_only(self):
        """1. OutOfMemoryError: Java heap space -> status=PLAN_ONLY, single recipe, exit 3."""
        log = self._write_log("[18:00:00] [Server thread/ERROR]: java.lang.OutOfMemoryError: Java heap space\n")
        plan = build_fixplan(log)
        self.assertEqual(plan["status"], "PLAN_ONLY")
        self.assertEqual(plan["mode"], "offline_read_only")
        self.assertEqual(plan["applied"], False)
        self.assertEqual(len(plan["recipes"]), 1)
        self.assertEqual(plan["recipes"][0]["signal"], "out_of_memory")
        self.assertEqual(plan["recipes"][0]["id"], "raise-heap-within-host-budget")
        self.assertEqual(plan["recipes"][0]["evidence_lines"], [1])

        # Test CLI invocation via mc_operator
        buf = StringIO()
        with redirect_stdout(buf):
            code = mc_operator_main(["fixplan", str(log), "--json"])
        self.assertEqual(code, 3)
        res = json.loads(buf.getvalue())
        self.assertEqual(res["status"], "PLAN_ONLY")
        self.assertEqual(len(res["recipes"]), 1)
        self.assertEqual(res["recipes"][0]["signal"], "out_of_memory")

        # Test CLI invocation via totem_repair_recipes
        buf2 = StringIO()
        with redirect_stdout(buf2):
            code2 = repair_main([str(log), "--json"])
        self.assertEqual(code2, 3)
        res2 = json.loads(buf2.getvalue())
        self.assertEqual(res2["status"], "PLAN_ONLY")

    def test_02_duplicate_signals_deduplication(self):
        """2. Three repeated NoClassDefFoundError lines -> single missing_class recipe, 3 evidence lines."""
        content = (
            "[10:00:01] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n"
            "[10:00:02] [main/INFO]: Some neutral message\n"
            "[10:00:03] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n"
            "[10:00:04] [main/WARN]: Warning line\n"
            "[10:00:05] [main/ERROR]: java.lang.NoClassDefFoundError: foo/Bar\n"
        )
        log = self._write_log(content)
        plan = build_fixplan(log)
        self.assertEqual(plan["status"], "PLAN_ONLY")
        self.assertEqual(len(plan["recipes"]), 1)
        self.assertEqual(plan["recipes"][0]["signal"], "missing_class")
        self.assertEqual(plan["recipes"][0]["evidence_lines"], [1, 3, 5])

        # Test evidence line capping at 20
        repeat_25 = "\n".join(["java.lang.NoClassDefFoundError: foo/Bar"] * 25) + "\n"
        log25 = self._write_log(repeat_25, name="log25.log")
        plan25 = build_fixplan(log25)
        self.assertEqual(len(plan25["recipes"][0]["evidence_lines"]), 20)

    def test_03_irrelevant_content_no_recipe(self):
        """3. Irrelevant content (Hello world) -> status=NO_RECIPE, recipes=[], exit 3."""
        content = (
            "[10:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
            "[10:00:05] [Server thread/INFO]: Hello world\n"
            "[10:00:10] [Server thread/INFO]: Done (5.0s)! For help, type 'help'\n"
        )
        log = self._write_log(content)
        plan = build_fixplan(log)
        self.assertEqual(plan["status"], "NO_RECIPE")
        self.assertEqual(plan["recipes"], [])

        buf = StringIO()
        with redirect_stdout(buf):
            code = mc_operator_main(["fixplan", str(log), "--json"])
        self.assertEqual(code, 3)
        res = json.loads(buf.getvalue())
        self.assertEqual(res["status"], "NO_RECIPE")
        self.assertEqual(res["recipes"], [])

    def test_04_nonexistent_and_directory_path_block(self):
        """4. Nonexistent path -> BLOCK, exit 2; directory path -> BLOCK, exit 2."""
        nonexistent = self.root / "does_not_exist.log"

        # Nonexistent via mc_operator
        buf1 = StringIO()
        with redirect_stdout(buf1):
            code1 = mc_operator_main(["fixplan", str(nonexistent), "--json"])
        self.assertEqual(code1, 2)
        res1 = json.loads(buf1.getvalue())
        self.assertEqual(res1["status"], "BLOCK")

        # Nonexistent via totem_repair_recipes
        buf2 = StringIO()
        with redirect_stdout(buf2):
            code2 = repair_main([str(nonexistent), "--json"])
        self.assertEqual(code2, 2)
        res2 = json.loads(buf2.getvalue())
        self.assertEqual(res2["status"], "BLOCK")

        # Directory via mc_operator
        buf3 = StringIO()
        with redirect_stdout(buf3):
            code3 = mc_operator_main(["fixplan", str(self.root), "--json"])
        self.assertEqual(code3, 2)
        res3 = json.loads(buf3.getvalue())
        self.assertEqual(res3["status"], "BLOCK")

        # Directory via totem_repair_recipes
        buf4 = StringIO()
        with redirect_stdout(buf4):
            code4 = repair_main([str(self.root), "--json"])
        self.assertEqual(code4, 2)
        res4 = json.loads(buf4.getvalue())
        self.assertEqual(res4["status"], "BLOCK")

    def test_05_catalog_integrity(self):
        """5. Catalog integrity: 1-to-1 with PATTERNS, unique IDs, steps 3-6, step 1 may_change_files False."""
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
        self.assertEqual(catalog["schema"], "totemops.repair_recipes/1")

        recipes = catalog["recipes"]
        expected_signals = {kind for kind, _, _ in PATTERNS}
        actual_signals = {r["signal"] for r in recipes}
        self.assertEqual(actual_signals, expected_signals)
        self.assertEqual(len(recipes), len(expected_signals))

        ids = [r["id"] for r in recipes]
        self.assertEqual(len(ids), len(set(ids)), "Recipe IDs must be strictly unique")

        for r in recipes:
            steps = r["steps"]
            self.assertGreaterEqual(len(steps), 3)
            self.assertLessEqual(len(steps), 6)
            self.assertEqual(steps[0]["order"], 1)
            self.assertFalse(steps[0]["may_change_files"])
            self.assertFalse(steps[0]["requires_confirmation"])
            self.assertEqual(steps[0]["risk"], "low")

        # Test failure modes of load_catalog
        bad_json = self.root / "bad.json"
        bad_json.write_text("{not_json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_catalog(bad_json)

        missing = self.root / "missing.json"
        with self.assertRaises(ValueError):
            load_catalog(missing)

        wrong_schema = self.root / "wrong_schema.json"
        wrong_schema.write_text(json.dumps({"schema": "wrong/1", "recipes": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_catalog(wrong_schema)

    def test_06_safety_rules(self):
        """6. Safety: modifying steps risk != low; each recipe do_not >= 2 and includes world/bulk disable."""
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
        for r in catalog["recipes"]:
            for step in r["steps"]:
                if step.get("may_change_files") or step.get("requires_confirmation"):
                    self.assertNotEqual(
                        step.get("risk"),
                        "low",
                        f"Recipe {r['id']} step {step['order']} modifies files or requires confirmation but has risk low",
                    )

            do_not = r["do_not"]
            self.assertGreaterEqual(len(do_not), 2, f"Recipe {r['id']} must have at least 2 do_not rules")

            all_dn_text = " ".join(
                f"{item.get('zh-TW', '')} {item.get('en', '')}" for item in do_not
            ).lower()
            self.assertTrue(
                "world" in all_dn_text,
                f"Recipe {r['id']} do_not must mention protecting world directory",
            )
            self.assertTrue(
                "bulk" in all_dn_text or "一次停用全部" in all_dn_text or "disable all" in all_dn_text,
                f"Recipe {r['id']} do_not must mention avoiding bulk mod disabling",
            )

    def test_07_privacy_guarantee(self):
        """7. Privacy: JSON output string must not contain raw log unique strings or tempdir paths."""
        secret_token = "SECRET_TOKEN_ABC_98765"
        sensitive_ip = "192.168.100.200"
        sensitive_user = "secret_user_xyz"
        content = (
            f"[12:00:00] [main/ERROR]: user={sensitive_user} token={secret_token} ip={sensitive_ip}\n"
            f"[12:00:01] [main/ERROR]: java.lang.OutOfMemoryError: Java heap space for {secret_token}\n"
        )
        log = self._write_log(content)
        buf = StringIO()
        with redirect_stdout(buf):
            mc_operator_main(["fixplan", str(log), "--json"])
        output_str = buf.getvalue()

        self.assertNotIn(secret_token, output_str)
        self.assertNotIn(sensitive_ip, output_str)
        self.assertNotIn(sensitive_user, output_str)
        self.assertNotIn(str(self.root), output_str)
        self.assertNotIn(str(log.resolve()), output_str)

    def test_08_determinism_and_order(self):
        """8. Determinism: same log twice produces identical JSON; recipes ordered by PATTERNS."""
        content = (
            # Intentionally put out_of_memory first, missing_class second, mixin third in log
            "[12:00:01] [main/ERROR]: java.lang.OutOfMemoryError: Java heap space\n"
            "[12:00:02] [main/ERROR]: java.lang.NoClassDefFoundError: net/foo/Bar\n"
            "[12:00:03] [main/ERROR]: org.spongepowered.asm.mixin.transformer.throwables.MixinApplyError: mixin.core\n"
        )
        log = self._write_log(content)
        plan1 = build_fixplan(log)
        plan2 = build_fixplan(log)

        json1 = json.dumps(plan1, sort_keys=True, separators=(",", ":"))
        json2 = json.dumps(plan2, sort_keys=True, separators=(",", ":"))
        self.assertEqual(json1, json2)

        # In PATTERNS, mixin_injection_failure is before missing_class, which is before out_of_memory
        recipe_signals = [r["signal"] for r in plan1["recipes"]]
        self.assertEqual(
            recipe_signals,
            ["mixin_injection_failure", "missing_class", "out_of_memory"],
        )

    def test_09_clean_json_output(self):
        """9. --json mode stdout must be a single parseable JSON object with no extra noise."""
        log = self._write_log("java.lang.OutOfMemoryError: Java heap space\n")
        buf = StringIO()
        with redirect_stdout(buf):
            repair_main([str(log), "--json"])
        raw = buf.getvalue().strip()
        self.assertTrue(raw.startswith("{"))
        self.assertTrue(raw.endswith("}"))
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)
        self.assertIn("status", parsed)
        self.assertIn("recipes", parsed)

    def test_10_human_readable_text_output(self):
        """Human-readable text mode (without --json) outputs structured zh-TW fixplan."""
        log = self._write_log("java.lang.OutOfMemoryError: Java heap space\n")
        buf = StringIO()
        with redirect_stdout(buf):
            code = repair_main([str(log)])
        self.assertEqual(code, 3)
        text = buf.getvalue()
        self.assertIn("【TotemOps 修復處方（Fixplan）】", text)
        self.assertIn("提高記憶體上限", text)
        self.assertIn("嚴禁操作", text)

    def test_11_unmatched_signal_review_required(self):
        """Unmatched signals in log escalate status to REVIEW_REQUIRED."""
        log = self._write_log("Dummy log\n")
        with patch("totem_repair_recipes.inspect_log") as mock_inspect:
            mock_inspect.return_value = {
                "file_sha256": "dummy_sha",
                "signals": [{"kind": "unsupported_exotic_signal", "line": 42}],
            }
            plan = build_fixplan(log)
            self.assertEqual(plan["status"], "REVIEW_REQUIRED")
            self.assertEqual(plan["unmatched_signals"], ["unsupported_exotic_signal"])


    def test_12_cli_respects_json_flag(self):
        """mc_operator entrypoint: no --json -> human zh-TW plan; --json -> single JSON doc."""
        log = self._write_log("java.lang.OutOfMemoryError: Java heap space\n")

        buf = StringIO()
        with redirect_stdout(buf):
            code = mc_operator_main(["fixplan", str(log)])
        self.assertEqual(code, 3)
        self.assertIn("【TotemOps 修復處方（Fixplan）】", buf.getvalue())
        self.assertNotIn('{"applied"', buf.getvalue())

        buf = StringIO()
        with redirect_stdout(buf):
            code = mc_operator_main(["fixplan", str(log), "--json"])
        self.assertEqual(code, 3)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["status"], "PLAN_ONLY")


if __name__ == "__main__":
    unittest.main()
