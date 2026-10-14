# SPDX-License-Identifier: Apache-2.0
"""Fast stage-only contract tests; no Docker network or real Minecraft install."""
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_operator import solve_and_verify


class StageFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name)
        self.log = self.parent / "latest.log"
        self.log.write_text("java.lang.NoClassDefFoundError: dev/example/Library\n")
        self.sandbox = self.parent / "agy-sandbox"
        self.sandbox.mkdir()
        (self.sandbox / ".agy-manager-sandbox").write_text("AGY_TEST_SANDBOX_V1\n")
        self.calls = []
        gate = patch("totem_env.preflight", return_value={"status": "ALLOW", "blockers": []})
        gate.start()
        self.addCleanup(gate.stop)

    def _fake_docker(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, "sha256:abc123\n", "")
        if args[:2] == ["docker", "run"] and "--entrypoint" in args:
            mount = args[args.index("--mount")+1]
            self.assertIn(",dst=/staging", mount)
            self.assertIn("--read-only", args)
            self.assertIn("--cap-drop", args)
            self.assertIn("ALL", args)
            self.assertIn("no-new-privileges", args)
            self.assertNotIn("--privileged", args)
            self.assertFalse(any("docker.sock" in str(x) for x in args))
            root = Path(mount.split("src=")[1].split(",dst=")[0])
            jar_dir = root / "mods"
            jar_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(jar_dir / "waystones.jar", "w") as f:
                f.writestr("META-INF/neoforge.mods.toml",
                          'modLoader="javafml"\n[[mods]]\nmodId="waystones"\nversion="21.1.46"\n')
            with zipfile.ZipFile(jar_dir / "balm.jar", "w") as f:
                f.writestr("META-INF/neoforge.mods.toml",
                          'modLoader="javafml"\n[[mods]]\nmodId="balm"\nversion="21.0.66"\n')
            return subprocess.CompletedProcess(args, 0, b"download complete", b"")
        self.fail("stage-only launched an unexpected process")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_stage_only_pinned_replay_and_cleanup(self, _):
        with patch("subprocess.run", side_effect=self._fake_docker):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, max_wait=100,
                version_id="6Z6MQ6os", stage_only=True)
        self.assertEqual(result["status"], "STAGED_ONLY")
        self.assertEqual(result["staged_count"], 2)
        self.assertEqual(len(result["staged_jars"][0]["sha256"]), 64)
        self.assertEqual(result["docker_image_digest"], "sha256:abc123")
        self.assertFalse(result["sandbox_verified"])
        self.assertFalse(result["production_modified"])
        self.assertEqual(result["replay"]["version_id"], "6Z6MQ6os")
        self.assertFalse(any(p[:3] == ["docker", "run", "-d"] for p in self.calls))
        self.assertEqual([p.name for p in self.sandbox.iterdir()],
                         [".agy-manager-sandbox"])
        helpers = [x for x in self.calls if "--entrypoint" in x]
        self.assertEqual(len(helpers), 1)
        self.assertIn("--projects=waystones:6Z6MQ6os", helpers[0])
        self.assertIn("--download-dependencies=REQUIRED", helpers[0])

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_container_readiness_receipt_and_cleanup(self, _):
        def fake_run(args, **kwargs):
            if args[:2] == ["docker", "run"] and "-d" in args:
                self.calls.append(args)
                self.assertIn("--memory", args)
                self.assertIn("--cpus", args)
                self.assertIn("--read-only", args)
                self.assertIn("--cap-drop", args)
                self.assertIn("no-new-privileges", args)
                self.assertIn("--user", args)
                self.assertIn("SKIP_NSSWITCH_CONF=TRUE", args)
                self.assertIn("SKIP_CHOWN_DATA=TRUE", args)
                self.assertNotIn("--privileged", args)
                self.assertFalse(any("docker.sock" in str(x) for x in args))
                self.assertNotIn("-p", args)
                return subprocess.CompletedProcess(args, 0, b"fake_container_id\n", b"")
            if args[:2] == ["docker", "exec"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, '{"server_info":{"version":{"name":"1.21.1","protocol":767}}}', "")
            if args[:2] == ["docker", "stop"] or args[:2] == ["docker", "rm"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return self._fake_docker(args, **kwargs)
        with patch("subprocess.run", side_effect=fake_run):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, max_wait=100, version_id="6Z6MQ6os")
        self.assertEqual(result["status"], "VERIFIED_ON_SANDBOX")
        self.assertTrue(result["sandbox_verified"])
        self.assertFalse(result["production_modified"])
        self.assertTrue(any(x[:2] == ["docker", "stop"] for x in self.calls))
        self.assertTrue(any(x[:2] == ["docker", "rm"] for x in self.calls))
        self.assertEqual([p.name for p in self.sandbox.iterdir()], [".agy-manager-sandbox"])

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_crashed_server_reports_block_and_still_cleans(self, _):
        def fake_run(args, **kwargs):
            if args[:2] == ["docker", "run"] and "-d" in args:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, b"fake_container_id\n", b"")
            if args[:2] == ["docker", "exec"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 1, b"", b"refused")
            if args[:2] == ["docker", "inspect"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, "false\n", "")
            if args[:2] == ["docker", "logs"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, "NeoForge mod loading\n", "")
            if args[:2] in (["docker", "stop"], ["docker", "rm"]):
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return self._fake_docker(args, **kwargs)
        with patch("subprocess.run", side_effect=fake_run):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, max_wait=100, version_id="6Z6MQ6os")
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "sandbox_server_exited")
        self.assertFalse(result["sandbox_verified"])
        self.assertTrue(any(x[:2] == ["docker", "stop"] for x in self.calls))

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_exact_receipt_replay_matches_pinned_files(self, _):
        with patch("subprocess.run", side_effect=self._fake_docker):
            baseline = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True)
        self.assertEqual(baseline["status"], "STAGED_ONLY")
        receipt = self.parent / "baseline.json"
        receipt.write_text(__import__("json").dumps(baseline))
        with patch("subprocess.run", side_effect=self._fake_docker):
            replay = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True,
                expected_receipt=receipt)
        self.assertEqual(replay["status"], "STAGED_ONLY")
        self.assertTrue(replay["receipt_match"])
        self.assertEqual(len(replay["expected_receipt_sha256"]), 64)

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_replay_detects_artifact_drift(self, _):
        with patch("subprocess.run", side_effect=self._fake_docker):
            baseline = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True)
        baseline["staged_jars"][0]["sha256"] = "0" * 64
        receipt = self.parent / "old.json"
        receipt.write_text(__import__("json").dumps(baseline))
        with patch("subprocess.run", side_effect=self._fake_docker):
            replay = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True,
                expected_receipt=receipt)
        self.assertEqual(replay["status"], "BLOCK")
        self.assertEqual(replay["reason"], "artifact_sha256_drift")

    def test_replay_rejects_wrong_version_before_network(self):
        import json
        receipt = self.parent / "wrong.json"
        receipt.write_text(json.dumps({"status": "STAGED_ONLY",
                         "candidate": {"project": "waystones", "version_id": "otherID",
                                       "game_version": "1.21.1", "loader": "neoforge"},
                         "staged_jars": [{"name": "a.jar", "sha256": "a" * 64}]}))
        with patch("subprocess.run") as sub:
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True,
                expected_receipt=receipt)
            sub.assert_not_called()
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "invalid_or_mismatched_expected_receipt")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_loader_seed_selected_and_exact_version_pinned(self, _):
        from unittest.mock import patch as monkey
        def run_server(args, **kwargs):
            if args[:2] == ["docker", "run"] and "-d" in args:
                self.assertIn("NEOFORGE_VERSION=21.1.259", args)
                return subprocess.CompletedProcess(args, 0, b"container", b"")
            if args[:2] == ["docker", "exec"]:
                return subprocess.CompletedProcess(
                    args, 0, '{"server_info":{"version":{"name":"1.21.1","protocol":767}}}', "")
            if args[:2] in (["docker","stop"], ["docker","rm"]):
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return self._fake_docker(args, **kwargs)
        with monkey("totem_runtime_seed.prepare_seed",
                    return_value={"status":"LOCAL_LOADER_CLONE", "copy_seconds":1.3}) as seed:
            with monkey("subprocess.run", side_effect=run_server):
                result=solve_and_verify(
                    self.log,"waystones","1.21.1","neoforge",self.sandbox,
                    execute_sandbox=True,version_id="6Z6MQ6os",
                    loader_version="21.1.259",cold_baseline_seconds=100)
        self.assertEqual(seed.call_count,1)
        self.assertEqual(result["runtime_reuse"]["status"],"LOCAL_LOADER_CLONE")
        self.assertEqual(result["status"],"VERIFIED_ON_SANDBOX")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_protocol_mismatch_is_not_success(self, _):
        def run_server(args, **kwargs):
            if args[:2] == ["docker","run"] and "-d" in args:
                return subprocess.CompletedProcess(args,0,b"container",b"")
            if args[:2] == ["docker","exec"]:
                return subprocess.CompletedProcess(
                    args,0,'{"server_info":{"version":{"name":"1.21.2","protocol":768}}}',"")
            if args[:2] == ["docker","inspect"]:
                return subprocess.CompletedProcess(args,0,"false\n","")
            if args[:2] == ["docker","logs"]:
                return subprocess.CompletedProcess(args,0,"","")
            if args[:2] in (["docker","stop"],["docker","rm"]):
                return subprocess.CompletedProcess(args,0,b"","")
            return self._fake_docker(args,**kwargs)
        with patch("subprocess.run",side_effect=run_server):
            result=solve_and_verify(
                self.log,"waystones","1.21.1","neoforge",self.sandbox,
                execute_sandbox=True,version_id="6Z6MQ6os")
        self.assertEqual(result["status"],"BLOCK")
        self.assertFalse(result["sandbox_verified"])

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_cas_import_then_restore_without_downloader(self, _):
        from totem_cas import stats
        with patch("subprocess.run", side_effect=self._fake_docker):
            baseline = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os",
                stage_only=True, cas_enabled=True)
        self.assertEqual(baseline["status"], "STAGED_ONLY")
        self.assertEqual(baseline["cas_store"]["new_blobs"], 2)
        self.assertEqual(stats(self.sandbox)["blobs"], 2)
        baseline["download_seconds"] = 15.0
        receipt = self.parent / "cas-stage.json"
        receipt.write_text(__import__("json").dumps(baseline))
        def fake_run_no_downloader(args, **kwargs):
            self.assertEqual(args[:3], ["docker", "image", "inspect"])
            return subprocess.CompletedProcess(args, 0, "sha256:abc123\n", "")
        with patch("subprocess.run", side_effect=fake_run_no_downloader) as calls:
            replay = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True,
                expected_receipt=receipt, cas_enabled=True)
        self.assertEqual(calls.call_count, 1)  # only cached Docker image identity
        self.assertEqual(replay["artifact_source"], "sha256_cas")
        self.assertTrue(replay["receipt_match"])
        self.assertEqual(replay["cas_lookup"]["status"], "CAS_RESTORED")
        self.assertEqual(replay["cas_store"]["existing_blobs"], 2)
        self.assertEqual(replay["download_seconds"], 0)

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_hung_docker_start_returns_block_and_forces_cleanup(self, _):
        commands = []
        def run(args, **kwargs):
            commands.append(args)
            if args[:2] == ["docker", "run"] and "-d" in args:
                raise subprocess.TimeoutExpired(cmd=args, timeout=2)
            if args[:2] == ["docker", "rm"]:
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return self._fake_docker(args, **kwargs)
        with patch("subprocess.run", side_effect=run):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, max_wait=60, version_id="6Z6MQ6os")
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "sandbox_container_start_timeout_or_error")
        self.assertTrue(any(c[:3] == ["docker", "rm", "--force"] for c in commands))

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_monitor_timeout_returns_block_and_attempts_stop(self, _):
        commands = []
        def run(args, **kwargs):
            commands.append(args)
            if args[:2] == ["docker", "run"] and "-d" in args:
                return subprocess.CompletedProcess(args, 0, b"cid", b"")
            if args[:2] == ["docker", "exec"]:
                raise subprocess.TimeoutExpired(cmd=args, timeout=2)
            if args[:2] in (["docker", "stop"], ["docker", "rm"]):
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return self._fake_docker(args, **kwargs)
        with patch("subprocess.run", side_effect=run):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, max_wait=60, version_id="6Z6MQ6os")
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "monitor_unreachable_or_timed_out")
        self.assertTrue(any(c[:2] == ["docker", "stop"] for c in commands))

    def test_invalid_version_id_before_any_docker(self):
        with patch("subprocess.run") as sub:
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id=";sh bad", stage_only=True)
            sub.assert_not_called()
        self.assertEqual(result["reason"], "invalid_version_id")

    def test_stage_requires_explicit_sandbox_opt_in(self):
        with patch("subprocess.run") as sub:
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=False, version_id="6Z6MQ6os", stage_only=True)
            sub.assert_not_called()
        self.assertEqual(result["reason"], "stage_only_requires_execute_sandbox")

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_download_failure_stops_before_inspection(self, _):
        def fail_download(args, **kwargs):
            if args[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(args, 0, "sha256:abc123\n", "")
            return subprocess.CompletedProcess(args, 8, b"", b"no matched version")
        with patch("subprocess.run", side_effect=fail_download):
            result = solve_and_verify(
                self.log, "waystones", "1.21.1", "neoforge", self.sandbox,
                execute_sandbox=True, version_id="6Z6MQ6os", stage_only=True)
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "dependency_downloader_failed")
        self.assertEqual(result["download_exit_code"], 8)


if __name__ == "__main__":
    unittest.main()
