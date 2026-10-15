# SPDX-License-Identifier: Apache-2.0
"""Contract tests for low-context Agent Skills + compact CLI evidence.

Only disposable synthetic JAR fixtures; no network, production files or Docker.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "tools" / "totem_operator.py")]


def make_jar(path: Path, modid: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/neoforge.mods.toml",
                   'modLoader="javafml"\nloaderVersion="[1,)"\nlicense="MIT"\n'
                   + f'[[mods]]\nmodId="{modid}"\nversion="1.0"\n')


class SkillEntrypointTests(unittest.TestCase):
    def test_standard_skill_discovery_paths_and_canonical_link(self):
        main = ROOT / "SKILL.md"
        self.assertTrue(main.is_file())
        self.assertIn("name: totem-ops", main.read_text())
        self.assertLess(main.stat().st_size, 5000)
        for base in (".agents", ".claude"):
            wrapper = ROOT / base / "skills" / "totem-ops" / "SKILL.md"
            content = wrapper.read_text()
            self.assertTrue(content.startswith("---\n"))
            self.assertIn("name: totem-ops", content)
            self.assertIn("description:", content)
            self.assertIn("../../../SKILL.md", content)
            self.assertEqual((wrapper.parent / "../../../SKILL.md").resolve(), main.resolve())
            self.assertLess(wrapper.stat().st_size, 1200)

    def test_root_help_exposes_three_commands(self):
        proc = subprocess.run(CLI + ["--help"], cwd=ROOT,
                              capture_output=True, text=True, timeout=8)
        self.assertEqual(proc.returncode, 0)
        for command in ("manifest", "crash", "smoke"):
            self.assertIn(command, proc.stdout)

    def test_compact_manifest_keeps_nonzero_review_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_jar(root / "sample.jar", "sample")
            full = subprocess.run(CLI + ["manifest", str(root), "--json"],
                                  cwd=ROOT, capture_output=True,text=True,timeout=12)
            small = subprocess.run(CLI + ["manifest", str(root), "--json", "--summary"],
                                   cwd=ROOT,capture_output=True,text=True,timeout=12)
            self.assertEqual(full.returncode, 3)
            self.assertEqual(small.returncode,3)
            data = json.loads(small.stdout)
            self.assertEqual(data["status"],"REVIEW_REQUIRED")
            self.assertFalse(data["release_allowed"])
            self.assertEqual(data["files_analyzed"],1)
            self.assertIn("full_report_sha256",data)
            self.assertLess(len(small.stdout),len(full.stdout))
            self.assertNotIn("md5_legacy",small.stdout)
            self.assertNotIn("sample.jar",small.stdout)

    def test_compact_manifest_fails_closed_for_rejected_jar(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bad.jar").write_bytes(b"bad jar")
            proc = subprocess.run(CLI + ["manifest",td,"--json","--summary"],
                                  cwd=ROOT,capture_output=True,text=True,timeout=12)
            self.assertEqual(proc.returncode,2)
            data = json.loads(proc.stdout)
            self.assertEqual(data["status"],"BLOCK")
            self.assertEqual(data["rejected_count"],1)
            self.assertFalse(data["release_allowed"])
            self.assertTrue(data["top_rejection_reasons"])

    def test_eighty_jar_summary_remains_small(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for n in range(80):
                make_jar(root / f"mod{n}.jar",f"mod{n}")
            proc = subprocess.run(CLI + ["manifest",str(root),"--summary"],
                                  cwd=ROOT,capture_output=True,text=True,timeout=18)
            self.assertEqual(proc.returncode,3,proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["files_analyzed"],80)
            self.assertLess(len(proc.stdout.encode("utf-8")),1050,
                            "The entire inventory must never fill the Agent context")


if __name__ == "__main__":
    unittest.main()
