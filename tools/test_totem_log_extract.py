# SPDX-License-Identifier: Apache-2.0
"""Tests for totem_log_extract: deterministic dependency inference and CLI integration."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from totem_log_extract import extract_missing_dependency
from mc_operator import main


class TotemLogExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _write_log(self, text: str | bytes, binary: bool = False) -> Path:
        p = self.root / f"test_{self._testMethodName}.log"
        if binary:
            p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        else:
            p.write_text(str(text), encoding="utf-8")
        return p

    def test_pattern_1_mod_a_requires_mod_b(self):
        log = self._write_log("Mod waystones requires mod balm to be installed\n")
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["project"], "balm")
        self.assertEqual(out["pattern"], "requires_mod")
        self.assertEqual(out["evidence_line"], 1)
        self.assertIn("Mod waystones requires mod balm", out["source_text"])

    def test_pattern_2_missing_mandatory_dependencies_block(self):
        log = self._write_log(
            "[18:42:13] [main/ERROR] [neoforge/]: Missing mandatory dependencies:\n"
            "\trequires mod balm\n"
        )
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["project"], "balm")
        self.assertEqual(out["pattern"], "missing_mandatory_dependencies")
        self.assertEqual(out["evidence_line"], 2)

    def test_pattern_3_missing_or_unsupported_mod_id(self):
        log = self._write_log(
            "Missing or unsupported mandatory dependencies:\n"
            "\tMod ID: 'balm', Requested by: 'waystones', Expected range: '[21.0.0,)'\n"
        )
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["project"], "balm")
        self.assertEqual(out["pattern"], "mod_id")
        self.assertEqual(out["evidence_line"], 2)

    def test_pattern_4_missing_or_unsupported_requires_mod(self):
        log = self._write_log(
            "Missing or unsupported mandatory dependencies:\n"
            "\tSome intermediate line\n"
            "\trequires mod balm\n"
        )
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["project"], "balm")
        self.assertEqual(out["pattern"], "missing_or_unsupported_mandatory_dependencies")
        self.assertEqual(out["evidence_line"], 3)

    def test_zero_candidates_review_required(self):
        log = self._write_log(
            "[18:42:13] [Server thread/INFO]: Starting minecraft server version 1.21.1\n"
            "[18:42:20] [Server thread/INFO]: Done (7.0s)! For help, type 'help'\n"
        )
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["reason"], "no_pattern_matched")
        self.assertEqual(out["candidates"], [])

    def test_multiple_candidates_review_required(self):
        log = self._write_log(
            "Mod waystones requires mod balm\n"
            "Mod journey requires mod cloth_config\n"
        )
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["reason"], "ambiguous_candidates")
        self.assertEqual(out["candidates"], ["balm", "cloth_config"])

    def test_super_long_line_handled_safely(self):
        long_line = "x" * 100000 + "\n"
        log = self._write_log(long_line + "Mod waystones requires mod balm\n")
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["project"], "balm")

    def test_binary_file_returns_block(self):
        log = self._write_log(b"\x00\x01\x02\x03\xff\xfe\xfd\x00", binary=True)
        out = extract_missing_dependency(log)
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["reason"], "log_unreadable")

    def test_cli_infer_project_single_candidate(self):
        log = self._write_log("Mod waystones requires mod balm to be installed\n")
        out_buf = StringIO()
        with redirect_stdout(out_buf):
            code = main([
                "solve-and-verify",
                "--log", str(log),
                "--infer-project",
                "--game-version", "1.21.1",
                "--loader", "neoforge",
            ])
        self.assertEqual(code, 3)  # PLAN_ONLY because sandbox not requested
        res = json.loads(out_buf.getvalue())
        self.assertEqual(res["status"], "PLAN_ONLY")
        self.assertEqual(res["candidate"]["project"], "balm")
        self.assertIn("project_inference", res)
        self.assertEqual(res["project_inference"]["project"], "balm")

    def test_cli_infer_project_ambiguous_blocks(self):
        log = self._write_log(
            "Mod waystones requires mod balm\n"
            "Mod journey requires mod cloth_config\n"
        )
        out_buf = StringIO()
        with redirect_stdout(out_buf):
            code = main([
                "solve-and-verify",
                "--log", str(log),
                "--infer-project",
                "--game-version", "1.21.1",
                "--loader", "neoforge",
            ])
        self.assertEqual(code, 2)  # BLOCK
        res = json.loads(out_buf.getvalue())
        self.assertEqual(res["status"], "BLOCK")
        self.assertEqual(res["reason"], "ambiguous_project_inference")
        self.assertEqual(res["candidates"], ["balm", "cloth_config"])

    def test_cli_infer_project_with_explicit_project_precedence(self):
        log = self._write_log("Mod waystones requires mod balm to be installed\n")
        out_buf = StringIO()
        with redirect_stdout(out_buf):
            code = main([
                "solve-and-verify",
                "--log", str(log),
                "--project", "explicit_mod",
                "--infer-project",
                "--game-version", "1.21.1",
                "--loader", "neoforge",
            ])
        self.assertEqual(code, 3)  # PLAN_ONLY
        res = json.loads(out_buf.getvalue())
        self.assertEqual(res["candidate"]["project"], "explicit_mod")
        self.assertIn("project_inference", res)
        self.assertEqual(res["project_inference"]["project"], "balm")


if __name__ == "__main__":
    unittest.main()
