# SPDX-License-Identifier: Apache-2.0
"""Value-first smoke tests for the thin mc_operator entrypoint."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_operator import diagnose, plan_deploy, summarize_package, main


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inspect_file_without_executing(self):
        p = self.root / "hello.jar"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("META-INF/mods.toml", '[\n'.replace('[\n', '') + '[[mods]]\nmodId="hello"\nversion="1.0.0"\n')
        out = summarize_package(p)
        self.assertEqual(out["mods"][0]["id"], "hello")
        self.assertEqual(out["maintenance"], "UNKNOWN_NOT_CHECKED_ONLINE")

    def test_diagnose_does_not_overclaim(self):
        path = self.root / "latest.log"
        path.write_text("java.lang.NoClassDefFoundError: dev/architectury/Foo\n")
        out = diagnose(path)
        self.assertEqual(out["confirmed_root_cause"], None)
        self.assertEqual(out["clues"][0]["status"], "SUSPECTED")
        self.assertNotIn("dev/architectury", json.dumps(out))

    def test_deploy_proposal_contains_expected_config(self):
        out = plan_deploy("1.21.1", "NEOFORGE", "8G", 25565)
        self.assertEqual(out["status"], "PLAN_ONLY")
        self.assertFalse(out["deployed"])
        self.assertIn('TYPE: "NEOFORGE"', out["compose"])
        self.assertIn('MEMORY: "8G"', out["compose"])

    def test_deploy_rejects_injected_version(self):
        self.assertEqual(plan_deploy("1.21.1\nports: 22", "NEOFORGE", "8G", 25565)["status"], "BLOCK")

    def test_deploy_rejects_absurd_memory(self):
        self.assertEqual(plan_deploy("1.21.1", "NEOFORGE", "999G", 25565)["status"], "BLOCK")

    def test_solve_and_verify_defaults_to_plan_only(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("java.lang.NoClassDefFoundError: dev/architectury/Foo\n")
        out = solve_and_verify(p, "architectury-api", "1.21.1", "neoforge", None)
        self.assertEqual(out["status"], "PLAN_ONLY")
        self.assertEqual(out["dependency_option"], "REQUIRED")
        self.assertFalse(out["sandbox_verified"])
        self.assertFalse(out["production_modified"])
        self.assertEqual(out["candidate"]["source"], "explicit_user_selection")
        self.assertIsNone(out["confirmed_root_cause"])

    def test_solve_with_only_log_is_not_an_auto_update(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("java.lang.OutOfMemoryError: Java heap space\n")
        out = solve_and_verify(p, None, None, None, None)
        self.assertEqual(out["status"], "PLAN_ONLY")
        self.assertIn("required", out["reason"])

    def test_solve_rejects_modrinth_command_injection(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        out = solve_and_verify(p, "x; rm -rf /", "1.21.1", "neoforge", None)
        self.assertEqual(out["status"], "BLOCK")

    def test_solve_rejects_non_sandbox_write_attempt(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        self.assertEqual(
            solve_and_verify(p, "architectury-api", "1.21.1", "neoforge",
                             self.root / "world", True)["reason"],
            "sandbox_root_not_allowlisted",
        )

    def test_sandbox_nested_inside_world_is_blocked_even_with_marker(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        sandbox = self.root / "world" / "agy-sandbox"
        sandbox.mkdir(parents=True)
        (sandbox / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n")
        out = solve_and_verify(p, "architectury-api", "1.21.1", "neoforge",
                               sandbox, True)
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["reason"], "sandbox_inside_protected_zone")

    def test_solve_rejects_missing_marker(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        sandbox = self.root / "agy-sandbox"
        sandbox.mkdir()
        out = solve_and_verify(p, "architectury-api", "1.21.1", "neoforge",
                               sandbox, True)
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["reason"], "sandbox_marker_missing")

    def test_solve_with_valid_marker_without_docker_is_explicit_block(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        sandbox = self.root / "agy-sandbox"
        sandbox.mkdir()
        (sandbox / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n")
        with patch("shutil.which", return_value=None), patch("totem_env.preflight", return_value={"status":"ALLOW","blockers":[]}):
            out = solve_and_verify(p, "architectury-api", "1.21.1", "neoforge",
                                   sandbox, True)
        self.assertEqual(out["status"], "BLOCK")
        self.assertEqual(out["reason"], "docker_not_installed")
        self.assertEqual(list(sandbox.iterdir()), [sandbox / ".agy-manager-sandbox"])

    def test_solve_timeout_capped(self):
        from mc_operator import solve_and_verify
        p = self.root / "crash.log"
        p.write_text("error\n")
        out = solve_and_verify(p, "architectury-api", "1.21.1", "neoforge",
                               None, False, 9999)
        self.assertEqual(out["status"], "BLOCK")

    def test_sync_not_fake_success(self):
        from contextlib import redirect_stdout
        from io import StringIO
        buf = StringIO()
        with redirect_stdout(buf):
            exitcode = main(["sync-publish"])
        self.assertEqual(exitcode, 2)
        self.assertEqual(json.loads(buf.getvalue())["action"], "no_network_request_sent")

    def test_inspect_untrusted_path_block(self):
        from contextlib import redirect_stdout
        from io import StringIO
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main(["inspect", "/does-not-exist/missing.jar"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(buf.getvalue())["status"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
