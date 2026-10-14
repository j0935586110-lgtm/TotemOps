#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps release assistant: read-only CurseForge pack + manual update audit.

Produces an owner-reviewable release plan, NEVER installs/uninstalls or connects to
public Minecraft servers. Reuses PCL/Prism/CurseForge for package downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

from mc_package_inspector import InputBlocked, _curseforge, _read_zipped, _sha256

MAX_ZIP_BYTES = 800 * 1024 * 1024
MAX_MEMBERS = 20000
MAX_EXPANDED_BYTES = 3_000_000_000
MAX_UPDATE_README = 65536
MAX_ITEM = 512 * 1024 * 1024
MANUAL_DELETE = re.compile(
    r"(?:移除|刪除|删除|remove)\s*(?:舊的)?\s*([A-Za-z0-9_.+\-]+\.jar)", re.I
)


def safe_relpath(s: str) -> str:
    """Reject paths which could escape the game instance on any common OS."""
    if (not isinstance(s, str) or not s or len(s) > 300
            or s.startswith(("/", "\\")) or "\\" in s
            or ":" in s.split("/")[0] or
            any(part in ("", ".", "..") for part in s.rstrip("/").split("/"))):
        raise InputBlocked("unsafe_release_archive_path")
    return s.rstrip("/")


def zip_inventory(path: Path) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ZIP_BYTES:
        raise InputBlocked("invalid_release_file")
    try:
        z = zipfile.ZipFile(path)
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
            raise InputBlocked("release_archive_limits")
        seen: set[str] = set()
        data = {}
        for info in infos:
            name = safe_relpath(info.filename)
            if info.file_size > MAX_ITEM:
                raise InputBlocked("release_member_too_large")
            key = name.lower()
            if key in seen:
                raise InputBlocked("release_duplicate_casefold_path")
            seen.add(key)
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                raise InputBlocked("release_symlink_member")
            if not info.is_dir():
                data[name] = info
        return z, data
    except (OSError, zipfile.BadZipFile) as exc:
        raise InputBlocked("invalid_release_zip") from exc
    except Exception:
        if "z" in locals():
            z.close()
        raise


def checksum(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with z.open(info) as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_payload_path(name: str) -> str | None:
    parts = name.split("/")
    for idx, part in enumerate(parts):
        if part in ("mods", "config", "kubejs", "shaderpacks", "resourcepacks"):
            return "/".join(parts[idx:])
    if parts[-1] == "servers.dat":
        return "servers.dat"
    return None


def inspect_release(pack: Path, update: Path | None = None) -> dict:
    pack_z, pack_files = zip_inventory(pack)
    try:
        if "manifest.json" not in pack_files:
            raise InputBlocked("curseforge_manifest_missing")
        meta = _curseforge(_read_zipped(pack_z, "manifest.json"))
        raw = json.loads(_read_zipped(pack_z, "manifest.json"))
        overrides = meta["overrides"] + "/"
        optional = [
            {"projectID": item["projectID"], "fileID": item["fileID"]}
            for item in raw["files"] if item["required"] is False
        ]
        out = {
            "status": "REVIEW_REQUIRED", "evidence": "PACKAGING_STATIC_ONLY",
            "action": "release_inspect",
            "pack": {"file": pack.name, "sha256": _sha256(pack), "name": meta["name"],
                     "version": meta["version"], "minecraft": meta["minecraft"],
                     "loaders": meta["mod_loaders"],
                     "required_external_files": meta["required_files"],
                     "optional_external_files": meta["optional_files"],
                     "archive_members": len(pack_files),
                     "external_files_downloaded": False},
            "optional_decisions": {
                "count": len(optional), "entries": optional[:100],
                "recommendation": "Owner must choose: make required, exclude, or keep selectable. "
                                  "Never silently change optional flags in the official manifest."
            },
            "update": None,
            "release_checks": [
                {"id": "EXTERNAL_DOWNLOAD", "result": "NOT_RUN",
                 "detail": "Manifest references are not the actual downloaded JARs"},
                {"id": "WINDOWS_INSTALL", "result": "NOT_RUN",
                 "detail": "Use the existing PCL/Prism game instance for a real install"},
                {"id": "GAME_LAUNCH", "result": "NOT_RUN",
                 "detail": "Java, GPU, authentication and actual gameplay not verified"},
            ],
            "write_performed": False, "updates_applied": False,
            "game_launched": False, "server_contacted": False,
        }
        if update is None:
            return out

        update_z, update_files = zip_inventory(update)
        try:
            readmes = [name for name, i in update_files.items()
                       if name.lower().endswith(("/readme.md", "/readme.txt"))
                       and i.file_size <= MAX_UPDATE_README]
            manual_removals: set[str] = set()
            for name in readmes:
                txt = update_z.read(name).decode("utf-8-sig", "replace")
                for m in MANUAL_DELETE.finditer(txt):
                    basename = m.group(1)
                    if "/" in basename or "\\" in basename:
                        raise InputBlocked("invalid_manual_removal_name")
                    manual_removals.add("mods/" + basename)
            operations = []
            comparisons = {"identical_to_full_overrides": 0,
                           "different_from_full_overrides": 0,
                           "absent_from_full_overrides": 0}
            for name, info in sorted(update_files.items()):
                target = find_payload_path(name)
                if target is None:
                    continue
                # This file is not installed. It is only a human-readable
                # proposal that must be applied by a separately authorised tool.
                entry = {"action": "COPY_AFTER_BACKUP", "from_update": name,
                         "target_game_relative": target, "bytes": info.file_size}
                if overrides + target in pack_files:
                    identical = checksum(update_z, info) == checksum(
                        pack_z, pack_files[overrides + target]
                    )
                    key = ("identical_to_full_overrides" if identical
                           else "different_from_full_overrides")
                else:
                    key = "absent_from_full_overrides"
                comparisons[key] += 1
                entry["compared_to_full_pack"] = key
                operations.append(entry)
            for target in sorted(manual_removals):
                operations.insert(0, {"action": "REMOVE_AFTER_BACKUP",
                                       "target_game_relative": target,
                                       "source": "update_readme_only"})
            out["update"] = {
                "file": update.name, "sha256": _sha256(update), "readmes_found": readmes,
                "manual_deletions": sorted(manual_removals),
                "copy_operations": sum(x["action"] == "COPY_AFTER_BACKUP" for x in operations),
                "operation_preview": operations[:100],
                "comparison": comparisons,
                "review_note": "The update ZIP is not a complete modpack. "
                               "Plan is not executed; paths only relative to a designated "
                               "test instance, and owner must approve deletion/overwrite."
            }
            if manual_removals:
                out["release_checks"].append({
                    "id": "MANUAL_UPDATER_FRICTION", "result": "ACTION_REQUIRED",
                    "detail": f"README requires {len(manual_removals)} explicit JAR removals"})
            return out
        finally:
            update_z.close()
    finally:
        pack_z.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="totem-ops release inspect")
    p.add_argument("--pack", type=Path, required=True)
    p.add_argument("--update", type=Path)
    args = p.parse_args(argv)
    try:
        result = inspect_release(args.pack, args.update)
    except (InputBlocked, OSError, ValueError, KeyError, TypeError,
            UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "BLOCK", "reason": str(exc)[:180],
                          "write_performed": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # REVIEW_REQUIRED is intentional; command executed successfully (no installs).
    return 0


if __name__ == "__main__":
    sys.exit(main())
