# SPDX-License-Identifier: Apache-2.0
"""Tests for mc_operator exit codes, receipt generation, and path safety gates."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

from mc_operator import main, compute_exit_code, write_receipt, _check_receipt_path_safety


class McOperatorExitCodesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.dummy_log = self.root / "latest.log"
        self.dummy_log.write_text("Dummy log\n", encoding="utf-8")

    def test_compute_exit_code_table(self):
        # 1. VERIFIED_ON_SANDBOX -> 0
        self.assertEqual(compute_exit_code({"status": "VERIFIED_ON_SANDBOX"}), 0)
        # 2. BLOCK -> 2
        self.assertEqual(compute_exit_code({"status": "BLOCK"}), 2)
        self.assertEqual(compute_exit_code({"code": "BLOCK"}), 2)
        # 3. PLAN_ONLY / STAGED_ONLY -> 3
        self.assertEqual(compute_exit_code({"status": "PLAN_ONLY"}), 3)
        self.assertEqual(compute_exit_code({"status": "STAGED_ONLY"}), 3)
        # 4. Other -> 5
        self.assertEqual(compute_exit_code({"status": "TIMEOUT"}), 5)
        self.assertEqual(compute_exit_code({"status": "UNKNOWN"}), 5)

    def test_compute_exit_code_require_verified(self):
        # With require_verified=True, non-VERIFIED returns 4
        self.assertEqual(compute_exit_code({"status": "PLAN_ONLY"}, require_verified=True), 4)
        self.assertEqual(compute_exit_code({"status": "STAGED_ONLY"}, require_verified=True), 4)
        self.assertEqual(compute_exit_code({"status": "BLOCK"}, require_verified=True), 4)
        self.assertEqual(compute_exit_code({"status": "TIMEOUT"}, require_verified=True), 4)
        # VERIFIED still returns 0
        self.assertEqual(compute_exit_code({"status": "VERIFIED_ON_SANDBOX"}, require_verified=True), 0)

    def run_cli(self, args):
        with redirect_stdout(StringIO()):
            return main(args)

    @patch("mc_operator.solve_and_verify")
    def test_cli_four_statuses_to_exit_codes(self, mock_solve):
        mock_solve.return_value = {"status": "VERIFIED_ON_SANDBOX", "sandbox_verified": True}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log)])
        self.assertEqual(code, 0)

        mock_solve.return_value = {"status": "BLOCK", "reason": "unauthorized"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log)])
        self.assertEqual(code, 2)

        mock_solve.return_value = {"status": "PLAN_ONLY", "reason": "sandbox_not_requested"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log)])
        self.assertEqual(code, 3)

        mock_solve.return_value = {"status": "STAGED_ONLY", "stage": "staged"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log)])
        self.assertEqual(code, 3)

        mock_solve.return_value = {"status": "TIMEOUT_WAITING", "stage": "booting"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log)])
        self.assertEqual(code, 5)

    @patch("mc_operator.solve_and_verify")
    def test_cli_require_verified_flag(self, mock_solve):
        mock_solve.return_value = {"status": "PLAN_ONLY", "reason": "sandbox_not_requested"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log), "--require-verified"])
        self.assertEqual(code, 4)

        mock_solve.return_value = {"status": "BLOCK", "reason": "safety_block"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log), "--require-verified"])
        self.assertEqual(code, 4)

        mock_solve.return_value = {"status": "VERIFIED_ON_SANDBOX"}
        code = self.run_cli(["solve-and-verify", "--log", str(self.dummy_log), "--require-verified"])
        self.assertEqual(code, 0)

    @patch("mc_operator.solve_and_verify")
    def test_receipt_file_written_atomically(self, mock_solve):
        mock_solve.return_value = {
            "status": "VERIFIED_ON_SANDBOX",
            "candidate": {"project": "balm", "game_version": "1.21.1"},
            "sandbox_verified": True,
        }
        receipt_path = self.root / "subdir" / "receipt.json"
        self.assertFalse(receipt_path.exists())

        code = self.run_cli([
            "solve-and-verify",
            "--log", str(self.dummy_log),
            "--receipt-out", str(receipt_path),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(receipt_path.is_file())

        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(data["receipt_schema"], 1)
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("created_at", data)
        self.assertIn("branch", data)
        self.assertEqual(data["status"], "VERIFIED_ON_SANDBOX")
        self.assertEqual(data["candidate"]["project"], "balm")

    def test_receipt_path_symlink_rejected(self):
        real_file = self.root / "real.json"
        real_file.write_text("{}", encoding="utf-8")
        symlink_path = self.root / "link_to_real.json"
        symlink_path.symlink_to(real_file)

        with self.assertRaises(ValueError):
            _check_receipt_path_safety(symlink_path)

        code = self.run_cli([
            "solve-and-verify",
            "--log", str(self.dummy_log),
            "--receipt-out", str(symlink_path),
        ])
        self.assertEqual(code, 2)

    def test_receipt_path_forbidden_dirs_rejected(self):
        for forbidden in ("/etc/malicious.json", "/usr/local/receipt.json", "/boot/receipt.json"):
            with self.assertRaises(ValueError):
                _check_receipt_path_safety(Path(forbidden))

            code = self.run_cli([
                "solve-and-verify",
                "--log", str(self.dummy_log),
                "--receipt-out", forbidden,
            ])
            self.assertEqual(code, 2)

        ssh_path = str(Path.home() / ".ssh" / "receipt.json")
        with self.assertRaises(ValueError):
            _check_receipt_path_safety(Path(ssh_path))

        code = self.run_cli([
            "solve-and-verify",
            "--log", str(self.dummy_log),
            "--receipt-out", ssh_path,
        ])
        self.assertEqual(code, 2)

    def test_receipt_path_relative_rejected(self):
        with self.assertRaises(ValueError):
            _check_receipt_path_safety(Path("relative/path.json"))

        code = self.run_cli([
            "solve-and-verify",
            "--log", str(self.dummy_log),
            "--receipt-out", "relative/path.json",
        ])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
