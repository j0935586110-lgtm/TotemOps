# SPDX-License-Identifier: Apache-2.0
"""Security and behavior tests for optional, no-paste mclo.gs adapter."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import urllib.error

path = Path(__file__).resolve().parent.parent / "plugins/mclogs-analyse/plugin.py"
spec = importlib.util.spec_from_file_location("mclogs_plugin", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

APPROVED = {"allow_external_processing": True, "user_reviewed_log_for_secrets": True}


class MclogsAdapterTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "latest.log"
        self.log = "Starting Minecraft server\nMissing mandatory dependency balm for waystones\n"
        self.path.write_text(self.log, encoding="utf-8")

    def request(self, **kw):
        return {"log_path": str(self.path), **kw}

    def test_without_both_consents_no_read_or_network(self):
        for args in ({}, {"allow_external_processing": True},
                     {"user_reviewed_log_for_secrets": True}):
            with patch.object(mod, "_call_mclogs") as external, patch.object(mod, "_read_log") as file:
                result = mod.analyse(self.request(**args))
            self.assertEqual(result["status"], "BLOCK")
            self.assertFalse(result["external_request_sent"])
            external.assert_not_called()
            file.assert_not_called()

    def test_success_reuses_provider_findings_no_unverified_success(self):
        body = {"analysis": {"problems": [{
            "message": "Missing Balm dependency", "counter": 2,
            "entry": {"lines": [{"number": 2, "content": self.log}]},
        }]}, "name": "NeoForge"}
        with patch.object(mod, "_call_mclogs", return_value=body) as external:
            out = mod.analyse(self.request(**APPROVED))
        external.assert_called_once_with(self.log)
        self.assertEqual(out["status"], "ANALYSIS_HINTS_ONLY")
        self.assertFalse(out["verified_root_cause"])
        self.assertFalse(out["modified_files"])
        self.assertFalse(out["saved_as_public_paste"])
        self.assertEqual(out["problems"][0]["evidence_line_numbers"], [2])
        self.assertNotIn(self.log, str(out))

    def test_sensitive_ip_blocks_before_post(self):
        self.path.write_text("Player connected from 192.168.1.22\n", encoding="utf-8")
        with patch.object(mod, "_call_mclogs") as external:
            out = mod.analyse(self.request(**APPROVED))
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["reason"], "sensitive_data_marker_found_review_and_redact_locally")
        external.assert_not_called()

    def test_tokens_private_key_blocks(self):
        samples = ["api_key=abcd1234", "Authorization: Bearer abcd123",
                   "-----BEGIN PRIVATE KEY-----\naaaaaaa"]
        for sample in samples:
            self.path.write_text(sample, encoding="utf-8")
            with patch.object(mod, "_call_mclogs") as external:
                out = mod.analyse(self.request(**APPROVED))
            self.assertEqual(out["status"], "BLOCK")
            external.assert_not_called()

    def test_symlink_is_blocked(self):
        link = self.path.with_name("alias.log")
        link.symlink_to(self.path)
        with patch.object(mod, "_call_mclogs") as external:
            out = mod.analyse({"log_path": str(link), **APPROVED})
        self.assertEqual(out["status"], "BLOCK")
        external.assert_not_called()

    def test_non_log_secret_file_denied(self):
        file = self.path.with_name("secret.json")
        file.write_text('{"password": "abc"}', encoding="utf-8")
        with patch.object(mod, "_call_mclogs") as external:
            out = mod.analyse({"log_path": str(file), **APPROVED})
        self.assertEqual(out["status"], "BLOCK")
        external.assert_not_called()

    def test_empty_too_large_and_bad_encoding(self):
        for data in (b"", b"x" * (mod.MAX_BYTES+1), b"\xff", b"\x00"):
            self.path.write_bytes(data)
            with patch.object(mod, "_call_mclogs") as external:
                result = mod.analyse(self.request(**APPROVED))
            self.assertEqual(result["status"], "BLOCK")
            external.assert_not_called()

    def test_failure_never_fabricates_provider_success(self):
        with patch.object(mod, "_call_mclogs", side_effect=urllib.error.URLError("timeout")):
            out = mod.analyse(self.request(**APPROVED))
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["external_request_sent"], "unknown")

    def test_no_valid_analysis_shape_fails_closed(self):
        with patch.object(mod, "_call_mclogs", return_value={"analysis": {"problems": "no"}}):
            out = mod.analyse(self.request(**APPROVED))
        self.assertEqual(out["status"], "BLOCK")
        self.assertTrue(out["external_request_sent"])

    def test_no_raw_lines_in_output_even_if_upstream_includes(self):
        with patch.object(mod, "_call_mclogs", return_value={"analysis": {"problems": [
            {"message": "Problem found", "entry": {"lines": [
                {"number": 3, "content": "Sensitive name of playerXYZ"}]}}
        ]}}):
            out = mod.analyse(self.request(**APPROVED))
        self.assertNotIn("playerXYZ", str(out))
        self.assertEqual(out["problems"][0]["evidence_line_numbers"], [3])


if __name__ == "__main__":
    import unittest
    unittest.main()
