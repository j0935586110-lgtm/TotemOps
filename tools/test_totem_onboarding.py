# SPDX-License-Identifier: Apache-2.0
"""Read-only onboarding doc-to-code checks for an arbitrary Python repo."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from totem_onboarding import analyze, OnboardingBlocked, main


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "main.py").write_text(
            'args = ["--auto", "--reconfig", "--dir"]\n'
            'print("--auto" in args)\n',
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            '## 用法\n--auto 啟動\n--reconf 設定\n'
            '## Python 編譯\npyinstaller --onefile --name x.py\n'
            '### PCL Launcher 啟動器\nTODO: 待補\n'
            '### Prism Launcher\n- 已有詳細使用說明\n', encoding="utf-8",
        )

    def test_typo_and_todo_are_actionable_with_lines(self):
        out = analyze(self.root, "main.py", "README.md")
        self.assertEqual(out["status"], "NEEDS_REVIEW")
        ids = {x["id"] for x in out["findings"]}
        self.assertEqual(ids, {"POSSIBLE_CLI_FLAG_TYPO", "LAUNCHER_GUIDE_TODO"})
        typo = next(x for x in out["findings"] if x["id"] == "POSSIBLE_CLI_FLAG_TYPO")
        self.assertEqual((typo["documented"], typo["closest_in_code"]), ("--reconf", "--reconfig"))
        self.assertEqual(typo["line"], 3)
        self.assertTrue(out["source"]["entry_sha256"])
        self.assertFalse(out["changes_made"])

    def test_no_false_failure_for_build_tool_flags(self):
        out = analyze(self.root, "main.py", "README.md")
        self.assertFalse(any(x.get("documented") in ("--onefile", "--name")
                             for x in out["findings"]))

    def test_no_todo_returns_clean_static_only(self):
        p = self.root / "README.md"
        p.write_text("### PCL Launcher\n預啟動設定範例：--auto\n", encoding="utf-8")
        out = analyze(self.root, "main.py", "README.md")
        self.assertEqual(out["status"], "NO_FINDINGS_STATIC_ONLY")
        self.assertFalse(out["guide_runtime_verified"])

    def test_other_project_todo_is_not_a_launcher_problem(self):
        (self.root / "README.md").write_text("## Not relevant\nTODO\n", encoding="utf-8")
        out = analyze(self.root, "main.py", "README.md")
        self.assertEqual(out["findings"], [])

    def test_rejects_readme_outside_repo(self):
        with self.assertRaisesRegex(OnboardingBlocked, "invalid_source_relative_path"):
            analyze(self.root, "main.py", "../secrets.md")

    def test_rejects_symlink_source(self):
        (self.root / "README.md").unlink()
        (self.root / "README.md").symlink_to(self.root / "main.py")
        with self.assertRaisesRegex(OnboardingBlocked, "source_symlink_blocked"):
            analyze(self.root, "main.py", "README.md")

    def test_rejects_intermediate_symlink(self):
        out = self.root / "elsewhere"
        out.mkdir()
        (out / "main.py").write_text('args=["--auto"]')
        (self.root / "src").symlink_to(out, target_is_directory=True)
        with self.assertRaisesRegex(OnboardingBlocked, "source_symlink_blocked"):
            analyze(self.root, "src/main.py", "README.md")

    def test_does_not_execute_python_source(self):
        p = self.root / "main.py"
        p.write_text("import os\nos.system('touch SHOULD_NOT_EXIST')\nargs=['--auto']\n")
        analyze(self.root, "main.py", "README.md")
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_invalid_syntax_is_blocked(self):
        (self.root / "main.py").write_text("def broken(:")
        with self.assertRaisesRegex(OnboardingBlocked, "invalid_python_entry_source"):
            analyze(self.root, "main.py", "README.md")

    def test_not_generic_unsupported_flag_alarm(self):
        (self.root / "README.md").write_text("## Usage\n--unrelated-to-the-source\n")
        out = analyze(self.root, "main.py", "README.md")
        self.assertFalse(any(x["id"] == "POSSIBLE_CLI_FLAG_TYPO"
                             for x in out["findings"]))


if __name__ == "__main__":
    unittest.main()
