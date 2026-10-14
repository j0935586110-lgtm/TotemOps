#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps beginner onboarding audit. Read only Markdown and Python AST.

It finds documented CLI flags that appear misspelled and unfinished setup
sections. Output is review evidence, not a statement that a launcher is broken.
"""
from __future__ import annotations
import argparse
import ast
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_TEXT = 500_000
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]{1,50}\b", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TODO = re.compile(r"\bTODO\b|\bTBD\b|待補|待完成", re.I)
LAUNCHER = re.compile(r"\bPCL\b|\bPrism\b|\bFjord\b|\bMultiMC\b|\bMinecraft Launcher\b", re.I)


class OnboardingBlocked(Exception):
    pass


def safe_source(root: Path, relative: str) -> tuple[str, str]:
    if (not isinstance(relative, str) or not relative or len(relative) > 180
            or "\\" in relative or relative.startswith("/")
            or ":" in relative.split("/")[0]
            or any(x in (".", "..", "") for x in relative.split("/"))):
        raise OnboardingBlocked("invalid_source_relative_path")
    source = root / relative
    # Block symlinks at every level, before canonicalizing the final path.
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise OnboardingBlocked("source_symlink_blocked")
    resolved = source.resolve()
    if not resolved.is_relative_to(root):
        raise OnboardingBlocked("source_outside_root")
    if not resolved.is_file() or resolved.stat().st_size > MAX_TEXT:
        raise OnboardingBlocked("source_missing_or_too_large")
    return resolved.read_text(encoding="utf-8"), hashlib.sha256(resolved.read_bytes()).hexdigest()


def git_head(root: Path) -> str | None:
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                           capture_output=True, text=True, timeout=4, check=False)
        return p.stdout.strip() if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", p.stdout.strip()) else None
    except (OSError, subprocess.SubprocessError):
        return None


def launch_sections(text: str, filename: str) -> list[dict]:
    """Only mark TODOs in launcher onboarding sections; ignore all other TODOs."""
    lines = text.splitlines()
    findings: list[dict] = []
    for i, line in enumerate(lines):
        m = HEADING.match(line.strip())
        if not m or not LAUNCHER.search(m.group(2)):
            continue
        level = len(m.group(1))
        end = len(lines)
        for k in range(i + 1, len(lines)):
            m2 = HEADING.match(lines[k].strip())
            if m2 and len(m2.group(1)) <= level:
                end = k
                break
        for k in range(i + 1, end):
            if TODO.search(lines[k]):
                findings.append({
                    "id": "LAUNCHER_GUIDE_TODO", "kind": "onboarding_gap",
                    "file": filename, "line": k + 1, "heading": m.group(2).strip(),
                    "evidence": lines[k].strip()[:180],
                    "next": "Complete a verified first-time setup example for this launcher",
                    "confidence": "HIGH", "runtime_tested": False,
                })
    return findings


def analyze(root: Path, entry: str, readme: str) -> dict:
    base = root.resolve()
    if not base.is_dir():
        raise OnboardingBlocked("repo_root_missing")
    code, code_sha = safe_source(base, entry)
    text, readme_sha = safe_source(base, readme)
    try:
        tree = ast.parse(code, filename=entry)
    except SyntaxError as exc:
        raise OnboardingBlocked("invalid_python_entry_source") from exc
    available: set[str] = set()
    for node in ast.walk(tree):
        # Only literal flags seen in production code; no running imported code.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if FLAG.fullmatch(val):
                available.add(val)
    findings = launch_sections(text, readme)
    for line_no, line in enumerate(text.splitlines(), 1):
        for documented in sorted(set(FLAG.findall(line))):
            if documented in available:
                continue
            closest = difflib.get_close_matches(documented, sorted(available), n=1, cutoff=0.72)
            # Unrelated flags may belong to e.g. pyinstaller in README; do not
            # claim that they are errors unless close to an actual code flag.
            if closest:
                findings.append({
                    "id": "POSSIBLE_CLI_FLAG_TYPO", "kind": "docs_code_mismatch",
                    "file": readme, "line": line_no, "documented": documented,
                    "closest_in_code": closest[0], "evidence": line.strip()[:180],
                    "next": "Confirm intended CLI spelling and correct docs or code",
                    "confidence": "MEDIUM", "runtime_tested": False,
                })
    return {
        "status": "NEEDS_REVIEW" if findings else "NO_FINDINGS_STATIC_ONLY",
        "evidence": "SOURCE_AND_DOCS_STATIC_ONLY", "source": {"repo": base.name,
            "git_head": git_head(base), "entry": entry, "entry_sha256": code_sha,
            "readme": readme, "readme_sha256": readme_sha},
        "known_cli_flags_in_entry": sorted(available),
        "findings": findings,
        "guide_runtime_verified": False, "website_tested": False,
        "changes_made": False, "remote_write": False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="totem-ops onboarding inspect",
                                description="Audit beginner setup doc/code drift (read-only)")
    p.add_argument("--repo-dir", type=Path, required=True)
    p.add_argument("--entry", default="main.py")
    p.add_argument("--readme", default="README.md")
    args = p.parse_args(argv)
    try:
        output = analyze(args.repo_dir, args.entry, args.readme)
    except (OnboardingBlocked, UnicodeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCK", "reason": str(exc)[:160],
                          "changes_made": False, "remote_write": False}))
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
