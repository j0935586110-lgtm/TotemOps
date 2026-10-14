#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps read-only repository maintainer: profile, provenance, CI checks.

Intentional non-features: no git clone, fetch, commit, push, remote write,
shell execution, downloading dependencies, or production-world access.
An already authorized Agent uses its own isolated worktree for code changes.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PROFILES=ROOT/"profiles"
SAFE_NAMES={"barian0517","chyuaner"}

class MaintainerBlock(Exception):
    pass

def profile(name):
    if name not in SAFE_NAMES:raise MaintainerBlock("unknown_profile")
    file=PROFILES/(name+".json")
    if file.is_symlink() or not file.is_file() or file.stat().st_size>24*1024:
        raise MaintainerBlock("profile_missing_or_unsafe")
    d=json.loads(file.read_text(encoding="utf-8"))
    if (not isinstance(d,dict) or d.get("schema")!=1
            or d.get("id")!=name or not isinstance(d.get("repositories"),list)):
        raise MaintainerBlock("invalid_profile")
    for repo in d["repositories"]:
        if not isinstance(repo,dict) or set(repo)!={"github","ref","sha","loader","minecraft","build","focus"}:
            raise MaintainerBlock("invalid_repository_descriptor")
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+",repo["github"]):
            raise MaintainerBlock("invalid_github_repo")
        if not re.fullmatch(r"[a-f0-9]{40}",repo["sha"]):
            raise MaintainerBlock("invalid_pinned_commit")
    return d

def command(*args,cwd):
    p=subprocess.run(["git","-c","core.fsmonitor=false","-c","gc.auto=0",
                      *args],cwd=str(cwd),capture_output=True,text=True,timeout=10)
    if p.returncode!=0:raise MaintainerBlock("git_inspection_failed")
    return p.stdout.strip()

def normalized_origin(raw):
    # Do not accept token-bearing URLs, arbitrary hosts, paths or query strings.
    patterns=(r"https://github[.]com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:[.]git)?/?",
              r"git@github[.]com:([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:[.]git)?")
    for pat in patterns:
        m=re.fullmatch(pat,raw)
        if m:return m.group(1)
    raise MaintainerBlock("untrusted_git_origin")

def ci_audit(root,branch):
    findings=[]
    folder=root/".github"/"workflows"
    if not folder.is_dir() or folder.is_symlink():return findings
    settings=root/"settings.gradle"
    modules=set()
    if settings.is_file() and not settings.is_symlink():
        s=settings.read_text(encoding="utf-8")[:100*1024]
        modules.update(re.findall(r"\binclude\s*\(?\s*['\"]([^'\"]+)['\"]",s))
    for wf in sorted(folder.glob("*"))[:40]:
        if wf.suffix.lower() not in (".yml",".yaml") or wf.is_symlink() or wf.stat().st_size>128*1024:continue
        lines=wf.read_text(encoding="utf-8").splitlines()
        # Only report a mismatch as a *candidate*: CI triggers may be
        # intentionally limited to an alternate base branch.
        for i,line in enumerate(lines,1):
            m=re.search(r"branches:\s*\[\s*['\"]?([A-Za-z0-9_./-]+)",line)
            if m and m.group(1)!=branch:
                findings.append({"kind":"workflow_branch_mismatch_candidate",
                                 "path":".github/workflows/"+wf.name,"line":i,
                                 "observed":m.group(1),"default_branch":branch,
                                 "verification":"STATIC_ONLY"})
            m=re.search(r"^\s*(?:-\s*)?run:\s*\./gradlew\s+(:[A-Za-z0-9_.-]+):([A-Za-z0-9_-]+)",line)
            if m and settings.is_file() and m.group(1) not in modules:
                findings.append({"kind":"gradle_unknown_project_candidate",
                                 "path":".github/workflows/"+wf.name,"line":i,
                                 "project":m.group(1),"task":m.group(2),
                                 "verification":"STATIC_ONLY"})
    return findings[:24]

def inspect(path,profile_name):
    d=profile(profile_name)
    root=Path(path).resolve()
    if root.is_symlink() or not root.is_dir():raise MaintainerBlock("invalid_repository_dir")
    gitroot=Path(command("rev-parse","--show-toplevel",cwd=root)).resolve()
    if gitroot!=root:raise MaintainerBlock("must_supply_git_root")
    remote=normalized_origin(command("config","--get","remote.origin.url",cwd=root))
    target=next((r for r in d["repositories"] if r["github"].lower()==remote.lower()),None)
    if not target:raise MaintainerBlock("repository_not_in_selected_profile")
    sha=command("rev-parse","HEAD",cwd=root)
    # Use profile ref as the expected CI target, not git's sometimes absent
    # local origin/HEAD symbolic ref on shallow repository checkouts.
    branch=target["ref"]
    changed=command("status","--porcelain","--untracked-files=normal",cwd=root)
    findings=ci_audit(root,branch)
    return {"status":"PASS" if sha==target["sha"] else "STALE_PROFILE",
            "mode":"READ_ONLY","profile":profile_name,
            "github":target["github"],"head":sha,
            "pinned_head":target["sha"],"head_matches_profile":sha==target["sha"],
            "expected_default_branch":branch,"dirty":bool(changed),
            "loader":target["loader"],"minecraft":target["minecraft"],
            "suggested_build":target["build"],"focus":target["focus"],
            "ci_findings":findings,"verification":"STATIC_ONLY",
            "build_executed":False,"changes_made":False,"remote_write":False}

def main(argv=None):
    p=argparse.ArgumentParser(description="TotemOps read-only repo-aware Agent support")
    sub=p.add_subparsers(dest="action",required=True)
    sub.add_parser("profiles")
    audit=sub.add_parser("inspect")
    audit.add_argument("--profile",required=True,choices=sorted(SAFE_NAMES))
    audit.add_argument("--repo-dir",required=True)
    o=p.parse_args(argv)
    try:
        if o.action=="profiles":
            r={"status":"PASS","profiles":[{"id":x,"repositories":[y["github"] for y in profile(x)["repositories"]]} for x in sorted(SAFE_NAMES)],"remote_write":False}
        else:r=inspect(o.repo_dir,o.profile)
    except (MaintainerBlock,OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as e:
        r={"status":"BLOCK","reason":str(e)[:140],"changes_made":False,"remote_write":False}
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 2 if r["status"] in ("BLOCK","STALE_PROFILE") else 0

if __name__=="__main__":raise SystemExit(main())
