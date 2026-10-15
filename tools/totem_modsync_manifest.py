#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only pre-publish inventory for Barian modsync-v2; NO deployment.

Reuse mc_package_inspector for bounded ZIP/TOML parsing and SHA-256;
MD5 is emitted solely to match the existing modsync-v2 HTTP inventory.
Unknown client/server execution side is NEVER inferred from folder names
or dependency-side metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mc_package_inspector import ENGINE_IDS, InputBlocked, MAX_FOLDER_FILES, inspect_one

SYNC_FOLDERS = ("mods", "clientmods", "needmods")
MAX_TOTAL_JARS = 300


class ManifestBlocked(ValueError):
    pass


def _md5_compat(path: Path) -> str:
    """Legacy wire-format digest, not a security integrity guarantee."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(folder: Path) -> list[Path]:
    if folder.is_symlink() or not folder.is_dir():
        raise ManifestBlocked("invalid_or_symlink_directory")
    # modsync-v2 explicitly supports subfolders. Traverse with strict bounds;
    # never follow symlinks or silently skip a nested JAR.
    pending = [(folder, 0)]
    visited, jars = 0, []
    while pending:
        parent, depth = pending.pop()
        if depth > 8:
            raise ManifestBlocked("folder_depth_limit")
        entries = sorted(parent.iterdir(), key=lambda p: p.name.casefold())
        visited += len(entries)
        if visited > 5000:
            raise ManifestBlocked("directory_entry_limit")
        for entry in entries:
            if entry.is_symlink():
                raise ManifestBlocked("symlink_disallowed")
            if entry.is_dir():
                pending.append((entry, depth + 1))
            elif entry.suffix.lower() == ".jar":
                if not entry.is_file():
                    raise ManifestBlocked("non_regular_jar")
                jars.append(entry)
                if len(jars) > MAX_FOLDER_FILES:
                    raise ManifestBlocked("too_many_packages")
    return sorted(jars, key=lambda p: p.relative_to(folder).as_posix().casefold())


def inspect_manifest(root: Path, layout: str = "flat") -> dict:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ManifestBlocked("invalid_or_symlink_root")
    if layout not in ("flat", "modsync-v2"):
        raise ManifestBlocked("unsupported_layout")
    folders = [("mods", root)] if layout == "flat" else [
        (name, root / name) for name in SYNC_FOLDERS if (root / name).exists()
    ]
    if layout == "modsync-v2":
        # Source WorkerThread checks 'needmods', while MainWindow text has
        # 'needsmods'. Do not silently normalize the incompatible spelling.
        if (root / "needsmods").exists() or (root / "needsmods").is_symlink():
            raise ManifestBlocked("ambiguous_needsmods_folder_name")
        if not folders:
            raise ManifestBlocked("no_modsync_v2_source_folders")
    paths = []
    for name, folder in folders:
        for path in _inventory(folder):
            paths.append((name, path))
    if not paths or len(paths) > MAX_TOTAL_JARS:
        raise ManifestBlocked("empty_or_oversized_jar_set")

    files, rejected, findings = [], [], []
    ids = {}
    loader_types = set()
    dependencies = []
    seen_casefold = set()
    for source_folder, jar in paths:
        relative = jar.relative_to(root).as_posix()
        normalized = relative.casefold()
        if normalized in seen_casefold:
            findings.append({"kind":"filename_case_collision", "file":relative, "severity":"block"})
        seen_casefold.add(normalized)
        try:
            package = inspect_one(jar)
            declared = [{
                "id": m["id"], "version": m["version"], "loader": m["loader"]
            } for m in package["mods"]]
            for mod in declared:
                ids.setdefault(mod["id"].casefold(), []).append(relative)
                loader_types.add(mod["loader"])
            dependencies.extend(package["dependencies"])
            files.append({
                "source_folder":source_folder, "path":relative,
                "md5_legacy":_md5_compat(jar),
                "sha256":package["sha256"], "mod_ids":declared,
                "execution_side":"UNKNOWN",
                "side_evidence":"not_inferable_from_sync_folder_or_dependency_side",
                "warnings":package["warnings"],
            })
            if package["warnings"] or not declared:
                findings.append({"kind":"metadata_needs_review", "file":relative, "severity":"review"})
        except (InputBlocked, OSError, ValueError, TypeError) as exc:
            rejected.append({"file":relative,"reason":str(exc)[:120]})

    for mod_id, locations in sorted(ids.items()):
        if len(locations) > 1:
            findings.append({"kind":"duplicate_mod_id", "id":mod_id,
                             "files":locations, "severity":"block"})
    mod_loaders = loader_types & {"forge","neoforge","fabric","quilt"}
    if len(mod_loaders) > 1:
        findings.append({"kind":"mixed_loaders", "loaders":sorted(mod_loaders),
                         "severity":"block"})
    for edge in dependencies:
        target = edge["to"].casefold()
        if edge["type"] == "incompatible" and target in ids:
            findings.append({"kind":"declared_incompatible", "from":edge["from"],
                             "to":edge["to"],"severity":"block"})
        if edge["type"] == "required" and target not in ids and target not in ENGINE_IDS:
            findings.append({"kind":"required_not_in_supplied_set", "from":edge["from"],
                             "to":edge["to"],"severity":"review",
                             "note":"not_proof_missing_from_final_installed_runtime"})
    # Preview Barian's /{folder}/?json=1 nested {filename: md5} shape.
    # This is NOT publishable: non-JAR config/kubejs and full upstream inventory
    # are not audited, and legacy MD5 alone is not tamper resistance.
    wire_preview = {}
    for item in files:
        folder_name = item["source_folder"]
        relative_parts = Path(item["path"]).parts
        if layout == "modsync-v2":
            relative_parts = relative_parts[1:]
        node = wire_preview.setdefault(folder_name, {})
        for segment in relative_parts[:-1]:
            node = node.setdefault(segment, {})
        node[relative_parts[-1]] = item["md5_legacy"]
    blocked = bool(rejected) or any(x["severity"] == "block" for x in findings)
    return {
        "schema":1, "status":"BLOCK" if blocked else "REVIEW_REQUIRED",
        "reason":"blocked_static_candidate" if blocked else "runtime_and_owner_review_required",
        "mode":"offline_read_only", "layout":layout, "files":files,
        "files_rejected":rejected, "findings":findings,
        "modsync_v2_inventory_preview":wire_preview,
        "sync_contract":{
            "source_folders":list(SYNC_FOLDERS) if layout == "modsync-v2" else ["mods"],
            "wire_inventory":"nested_json_file_path_to_md5",
            "inventory_written":False,
            "warning":"not_a_modsync_v2_server_api_response_or_install_manifest"
        },
        "checks_not_run":["java_loader_runtime","client_server_execution_side",
                          "complete_version_range_resolution","server_smoke",
                          "client_join","upstream_remote_sync_verification",
                          "manual_release_approval"],
        "publication_performed":False, "download_performed":False,
        "game_launched":False, "write_performed":False,
        "release_allowed":False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Minecraft pre-publish inventory")
    parser.add_argument("path",type=Path)
    parser.add_argument("--layout",choices=("flat","modsync-v2"),default="flat")
    parser.add_argument("--json",action="store_true",help="Emit JSON (default is also JSON)")
    parser.add_argument("--summary", action="store_true",
                        help="Bounded agent-facing JSON; no full JAR inventory")
    args = parser.parse_args(argv)
    try:
        result = inspect_manifest(args.path,layout=args.layout)
    except (ManifestBlocked, OSError, ValueError, TypeError) as exc:
        result = {"schema":1,"status":"BLOCK","reason":str(exc)[:170],
                  "release_allowed":False,"write_performed":False,
                  "publication_performed":False,"game_launched":False}
    if args.summary:
        # Full JSON remains obtainable separately; summaries do not contain
        # raw mod inventories, absolute paths, or unbounded findings.
        full = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",",":"))
        reasons = result.get("files_rejected", [])
        findings = result.get("findings", [])
        result = {
            "schema":1, "status": result["status"],
            "reason":result.get("reason", ""),
            "files_analyzed":len(result.get("files", [])),
            "rejected_count":len(reasons), "findings_count":len(findings),
            "top_findings":[{"kind":str(f.get("kind", ""))[:60],
                             "severity":str(f.get("severity", ""))[:20]}
                            for f in findings[:3]],
            "top_rejection_reasons":[str(f.get("reason", ""))[:80] for f in reasons[:3]],
            "truncated":len(findings)>3 or len(reasons)>3,
            "full_report_sha256":hashlib.sha256(full.encode("utf-8")).hexdigest(),
            "release_allowed":False,"publication_performed":False,
            "write_performed":False,
            "checks_not_run":result.get("checks_not_run", []),
        }
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    # REVIEW_REQUIRED is a non-green return; downstream CI cannot accidentally publish.
    return 2 if result["status"] == "BLOCK" else 3


if __name__ == "__main__":
    raise SystemExit(main())
