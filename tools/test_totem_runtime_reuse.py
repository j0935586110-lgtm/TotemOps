# SPDX-License-Identifier: Apache-2.0
"""Tests for NeoForge runtime seed reuse in solve-and-verify."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_operator import solve_and_verify


class TotemRuntimeReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.sandbox = Path(self.temp_dir.name) / "agy-sandbox"
        self.sandbox.mkdir()
        (self.sandbox / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n", encoding="utf-8")

        self.log = self.sandbox / "test.log"
        self.log.write_text("Mod waystones requires mod balm to be installed\n", encoding="utf-8")
        self.calls = []
        gate = patch("totem_env.preflight", return_value={"status": "ALLOW", "blockers": []})
        gate.start()
        self.addCleanup(gate.stop)

    def _fake_docker(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, "sha256:1111111111111111111111111111111111111111111111111111111111111111\n", "")

        # Downloader container
        if "--entrypoint" in args and "mc-image-helper" in args:
            for item in args:
                if item.startswith("--mount=type=bind,src=") or item.startswith("type=bind,src="):
                    part = item.split("src=")[1].split(",")[0]
                    src_dir = Path(part)
                    mods_dir = src_dir / "mods"
                    mods_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(mods_dir / "balm.jar", "w") as z:
                        z.writestr("META-INF/neoforge.mods.toml",
                                   'modLoader="javafml"\n[[mods]]\nmodId="balm"\nversion="21.0.66"\n')
                    break
            return subprocess.CompletedProcess(args, 0, b"download done", b"")

        # Ephemeral server container
        if args[:2] == ["docker", "run"] and "-d" in args:
            for item in args:
                if "src=" in item:
                    part = item.split("src=")[1].split(",")[0]
                    data_dir = Path(part)
                    # Create NeoForge runtime files
                    run_sh = data_dir / "run.sh"
                    if not run_sh.exists():
                        lib_dir = data_dir / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.259"
                        lib_dir.mkdir(parents=True, exist_ok=True)
                        (lib_dir / "unix_args.txt").write_text("--help", encoding="utf-8")
                        run_sh.write_text("java @libraries/net/neoforged/neoforge/21.1.259/unix_args.txt\n", encoding="utf-8")
                        (data_dir / ".neoforge-manifest.json").write_text(json.dumps({
                            "minecraftVersion": "1.21.1",
                            "forgeVersion": "21.1.259",
                            "serverEntry": "run.sh",
                        }), encoding="utf-8")
                    break
            return subprocess.CompletedProcess(args, 0, b"fake_container_id\n", b"")

        # mc-monitor query
        if args[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(args, 0, '{"server_info":{"version":{"name":"1.21.1","protocol":767}}}', "")

        # cleanup
        if args[:2] in (["docker", "stop"], ["docker", "rm"]):
            return subprocess.CompletedProcess(args, 0, b"", b"")

        return subprocess.CompletedProcess(args, 0, b"", b"")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_reuse_runtime_cycle_missing_then_stored_then_reused(self, _):
        # Call 1: seed does not exist -> MISSING, then after verified -> STORED
        with patch("subprocess.run", side_effect=self._fake_docker):
            res1 = solve_and_verify(
                log=self.log,
                project="balm",
                game_version="1.21.1",
                loader="neoforge",
                sandbox_root=self.sandbox,
                execute_sandbox=True,
                loader_version="21.1.259",
                reuse_runtime=True,
            )
        self.assertEqual(res1["status"], "VERIFIED_ON_SANDBOX")
        self.assertEqual(res1["runtime_reuse"]["decision"], "STORED")
        stored_path = Path(res1["runtime_reuse"]["path"])
        self.assertTrue(stored_path.is_dir())
        self.assertTrue((stored_path / "totemops-runtime-seed.json").is_file())

        # Call 2: seed exists -> REUSED
        with patch("subprocess.run", side_effect=self._fake_docker):
            res2 = solve_and_verify(
                log=self.log,
                project="balm",
                game_version="1.21.1",
                loader="neoforge",
                sandbox_root=self.sandbox,
                execute_sandbox=True,
                loader_version="21.1.259",
                reuse_runtime=True,
            )
        self.assertEqual(res2["status"], "VERIFIED_ON_SANDBOX")
        self.assertEqual(res2["runtime_reuse"]["decision"], "REUSED")
        self.assertEqual(res2["runtime_reuse"]["path"], str(stored_path))

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_reuse_runtime_missing_when_not_verified(self, _):
        def fake_fail(args, **kwargs):
            if args[:2] == ["docker", "exec"]:
                return subprocess.CompletedProcess(args, 1, b"", b"refused")
            if args[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(args, 0, "false\n", "")
            if args[:2] == ["docker", "logs"]:
                return subprocess.CompletedProcess(args, 0, "server died\n", "")
            return self._fake_docker(args, **kwargs)

        with patch("subprocess.run", side_effect=fake_fail):
            res = solve_and_verify(
                log=self.log,
                project="balm",
                game_version="1.21.1",
                loader="neoforge",
                sandbox_root=self.sandbox,
                execute_sandbox=True,
                loader_version="21.1.259",
                reuse_runtime=True,
            )
        self.assertEqual(res["status"], "BLOCK")
        self.assertEqual(res["runtime_reuse"]["decision"], "MISSING")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_reuse_runtime_corrupt_seed_blocks(self, _):
        # First create a valid seed
        with patch("subprocess.run", side_effect=self._fake_docker):
            res = solve_and_verify(
                log=self.log,
                project="balm",
                game_version="1.21.1",
                loader="neoforge",
                sandbox_root=self.sandbox,
                execute_sandbox=True,
                loader_version="21.1.259",
                reuse_runtime=True,
            )
        self.assertEqual(res["status"], "VERIFIED_ON_SANDBOX")
        stored_path = Path(res["runtime_reuse"]["path"])

        # Tamper with run.sh in the seed
        (stored_path / "run.sh").write_text("tampered content\n", encoding="utf-8")

        # Now try to reuse: must fail closed with BLOCK and reason runtime_seed_invalid
        with patch("subprocess.run", side_effect=self._fake_docker):
            corrupt_res = solve_and_verify(
                log=self.log,
                project="balm",
                game_version="1.21.1",
                loader="neoforge",
                sandbox_root=self.sandbox,
                execute_sandbox=True,
                loader_version="21.1.259",
                reuse_runtime=True,
            )
        self.assertEqual(corrupt_res["status"], "BLOCK")
        self.assertEqual(corrupt_res["reason"], "runtime_seed_invalid")


if __name__ == "__main__":
    unittest.main()
