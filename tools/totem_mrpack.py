#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""TotemOps Modrinth .mrpack index exporter and atomic packager.

Generates reproducible modrinth.index.json metadata and .mrpack archives.
Requires verified download sources; fail-closed against unverified sources,
unsafe URLs, symlinks, and path overwrites.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

try:
    from mc_package_inspector import _hashes
except ImportError:
    from tools.mc_package_inspector import _hashes

PACKINDEX_SCHEMA = "totemops.packindex/1"
NOT_VERIFIED_CHECKS = [
    "remote_modrinth_hash_lookup",
    "actual_launcher_install",
]


def is_safe_url(url: str) -> tuple[bool, str]:
    if not isinstance(url, str):
        return False, "url_not_a_string"
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False, "whitespace_or_control_chars"
    if not url.startswith("https://"):
        return False, "only_https_accepted"
    if "@" in url:
        return False, "credentials_in_url"
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return False, "url_parse_error"
    if parts.scheme != "https":
        return False, "scheme_not_https"
    hostname = parts.hostname
    if not hostname:
        return False, "missing_hostname"
    hostname = hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return False, "localhost_not_allowed"

    try:
        ipaddress.ip_address(hostname)
        return False, "pure_ip_not_allowed"
    except ValueError:
        pass

    if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
        return False, "pure_ip_not_allowed"
    if hostname.startswith("127.") or hostname.startswith("10.") or hostname.startswith("192.168."):
        return False, "private_ip_not_allowed"
    if re.match(r"^172\.(1[6-9]|2\d|3[01])\.", hostname):
        return False, "private_ip_not_allowed"
    return True, ""


def _check_output_path_safety(p: Path) -> tuple[bool, str]:
    if p.is_symlink() or os.path.islink(str(p)):
        return False, "symlink_not_allowed"
    if p.exists():
        return False, "output_exists"
    norm_p = os.path.abspath(str(p))
    forbidden_prefixes = ("/etc", "/usr", "/boot", "/sys", "/proc", "/dev", "/bin", "/sbin", "/lib", "/lib64")
    for pref in forbidden_prefixes:
        if norm_p == pref or norm_p.startswith(pref + "/"):
            return False, "output_path_rejected"
    try:
        home_ssh = os.path.abspath(str(Path.home() / ".ssh"))
    except (RuntimeError, OSError):
        home_ssh = None
    if home_ssh and (norm_p == home_ssh or norm_p.startswith(home_ssh + "/")):
        return False, "output_path_rejected"
    curr = p.parent
    while curr != curr.parent:
        if curr.is_symlink() or os.path.islink(str(curr)):
            return False, "symlink_not_allowed"
        if curr.exists():
            break
        curr = curr.parent
    return True, ""


def build_packindex(
    mods_dir: Path | str,
    name: str,
    version: str,
    minecraft: str,
    loader: str,
    downloads_map_path: Path | str | None = None,
    out_path: Path | str | None = None,
    side: str = "both",
) -> dict:
    side = side.lower().strip()
    if side not in ("both", "client", "server"):
        side = "both"

    if not isinstance(mods_dir, Path):
        mods_dir = Path(mods_dir)

    if mods_dir.is_symlink():
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "BLOCK",
            "reason": "symlink_not_allowed",
            "total_jars": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "next_step": "輸入目錄不得為符號連結",
        }

    if not mods_dir.is_dir():
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "BLOCK",
            "reason": "mods_dir_not_found",
            "total_jars": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "next_step": "請確認 mods 目錄是否存在且為有效資料夾",
        }

    jars: list[Path] = []
    for p in mods_dir.iterdir():
        if p.name.startswith("."):
            continue
        if p.suffix.lower() == ".jar":
            if p.is_symlink() or os.path.islink(str(p)):
                return {
                    "schema": PACKINDEX_SCHEMA,
                    "mode": "offline_read_only",
                    "status": "BLOCK",
                    "reason": "symlink_not_allowed",
                    "total_jars": 0,
                    "resolved_count": 0,
                    "unresolved_count": 0,
                    "unresolved": [],
                    "next_step": "JAR 檔案不得為符號連結",
                }
            jars.append(p)

    jars.sort(key=lambda p: p.name)
    if not jars:
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "BLOCK",
            "reason": "no_supported_packages",
            "total_jars": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "next_step": "mods 目錄中未發現有效的 .jar 檔案",
        }

    # Load and validate downloads_map
    downloads_map: dict[str, dict] = {}
    if downloads_map_path:
        dmap_p = Path(downloads_map_path) if not isinstance(downloads_map_path, Path) else downloads_map_path
        if dmap_p.is_symlink() or os.path.islink(str(dmap_p)):
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "symlink_not_allowed",
                "total_jars": len(jars),
                "resolved_count": 0,
                "unresolved_count": len(jars),
                "unresolved": [j.name for j in jars],
                "next_step": "downloads-map 檔案不得為符號連結",
            }
        if not dmap_p.is_file():
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "downloads_map_not_found",
                "total_jars": len(jars),
                "resolved_count": 0,
                "unresolved_count": len(jars),
                "unresolved": [j.name for j in jars],
                "next_step": "請確認 downloads-map 檔案路徑",
            }
        try:
            raw_map = json.loads(dmap_p.read_text(encoding="utf-8"))
        except Exception:
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "invalid_downloads_map",
                "total_jars": len(jars),
                "resolved_count": 0,
                "unresolved_count": len(jars),
                "unresolved": [j.name for j in jars],
                "next_step": "downloads-map 必須為有效的 JSON 物件",
            }
        if not isinstance(raw_map, dict):
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "invalid_downloads_map",
                "total_jars": len(jars),
                "resolved_count": 0,
                "unresolved_count": len(jars),
                "unresolved": [j.name for j in jars],
                "next_step": "downloads-map 必須為字典結構",
            }

        # Validate all entries and URLs (fail-closed)
        for fname, entry in raw_map.items():
            if not isinstance(entry, dict) or "url" not in entry:
                return {
                    "schema": PACKINDEX_SCHEMA,
                    "mode": "offline_read_only",
                    "status": "BLOCK",
                    "reason": "invalid_downloads_map",
                    "total_jars": len(jars),
                    "resolved_count": 0,
                    "unresolved_count": len(jars),
                    "unresolved": [j.name for j in jars],
                    "next_step": f"{fname} 缺少有效 url 欄位",
                }
            url = entry["url"]
            safe, url_reason = is_safe_url(url)
            if not safe:
                return {
                    "schema": PACKINDEX_SCHEMA,
                    "mode": "offline_read_only",
                    "status": "BLOCK",
                    "reason": f"invalid_download_url:{url_reason}",
                    "total_jars": len(jars),
                    "resolved_count": 0,
                    "unresolved_count": len(jars),
                    "unresolved": [j.name for j in jars],
                    "next_step": f"URL 安全閘拒絕：{url_reason}",
                }
        downloads_map = raw_map

    # Setup env
    if side == "both":
        env_dict = {"client": "required", "server": "required"}
    elif side == "client":
        env_dict = {"client": "required", "server": "unsupported"}
    elif side == "server":
        env_dict = {"client": "unsupported", "server": "required"}
    else:
        env_dict = {"client": "required", "server": "required"}

    resolved_files: list[dict] = []
    unresolved: list[str] = []

    for j in jars:
        fname = j.name
        fsize = j.stat().st_size
        h = _hashes(j)
        if fname in downloads_map:
            resolved_files.append({
                "path": f"mods/{fname}",
                "hashes": {
                    "sha1": h["sha1"],
                    "sha512": h["sha512"],
                },
                "env": env_dict,
                "downloads": [downloads_map[fname]["url"]],
                "fileSize": fsize,
            })
        else:
            unresolved.append(fname)

    resolved_files.sort(key=lambda x: x["path"])
    unresolved.sort()

    out_p: Path | None = None
    if out_path:
        out_p = Path(out_path) if not isinstance(out_path, Path) else out_path
        safe_out, out_reason = _check_output_path_safety(out_p)
        if not safe_out:
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": out_reason,
                "total_jars": len(jars),
                "resolved_count": len(resolved_files),
                "unresolved_count": len(unresolved),
                "unresolved": unresolved,
                "next_step": "輸出路徑不安全或已存在，請指定有效路徑",
            }

    # Case 1: Unresolved files present
    if unresolved:
        if out_p is not None:
            # When --out is given, must fail-closed without writing
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "downloads_unresolved",
                "total_jars": len(jars),
                "resolved_count": len(resolved_files),
                "unresolved_count": len(unresolved),
                "unresolved": unresolved,
                "next_step": "尚有模組未解析下載來源，拒絕寫出未完成的 .mrpack",
            }

        # No --out -> PLAN_ONLY
        index_draft = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": version,
            "name": name,
            "summary": "",
            "files": resolved_files,
            "dependencies": {
                "minecraft": minecraft,
                loader.lower(): "*",
            },
        }
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "PLAN_ONLY",
            "name": name,
            "version": version,
            "minecraft": minecraft,
            "loader": loader.lower(),
            "side": side,
            "total_jars": len(jars),
            "resolved_count": len(resolved_files),
            "unresolved_count": len(unresolved),
            "unresolved": unresolved,
            "index": index_draft,
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "請提供完整 downloads-map 後指定 --out 寫出 .mrpack",
        }

    # Case 2: All files resolved
    index_obj = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version,
        "name": name,
        "summary": "",
        "files": resolved_files,
        "dependencies": {
            "minecraft": minecraft,
            loader.lower(): "*",
        },
    }

    if out_p is None:
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "PLAN_ONLY",
            "name": name,
            "version": version,
            "minecraft": minecraft,
            "loader": loader.lower(),
            "side": side,
            "total_jars": len(jars),
            "resolved_count": len(resolved_files),
            "unresolved_count": 0,
            "unresolved": [],
            "index": index_obj,
            "not_verified": NOT_VERIFIED_CHECKS,
            "next_step": "所有模組已解析，可指定 --out 寫出 .mrpack",
        }

    # Write out atomically and read-back verify
    index_bytes = (json.dumps(index_obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile("wb", dir=out_p.parent, delete=False, suffix=".tmp")
    temp_name = temp_file.name
    try:
        with zipfile.ZipFile(temp_file, "w", zipfile.ZIP_DEFLATED) as z:
            zinfo = zipfile.ZipInfo("modrinth.index.json", (2026, 1, 1, 0, 0, 0))
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zinfo, index_bytes)
        temp_file.close()

        # Read back verification
        with zipfile.ZipFile(temp_name, "r") as z_read:
            if "modrinth.index.json" not in z_read.namelist():
                raise ValueError("missing_index_in_archive")
            raw_content = z_read.read("modrinth.index.json")
            loaded = json.loads(raw_content.decode("utf-8"))
            if loaded.get("formatVersion") != 1:
                raise ValueError("invalid_format_version")
            rf_list = loaded.get("files", [])
            if len(rf_list) != len(resolved_files):
                raise ValueError("file_count_mismatch")
            for rf, ef in zip(rf_list, resolved_files):
                if (
                    rf["path"] != ef["path"]
                    or rf["hashes"]["sha512"] != ef["hashes"]["sha512"]
                    or rf["fileSize"] != ef["fileSize"]
                ):
                    raise ValueError("hash_or_size_mismatch")

        if out_p.exists():
            os.unlink(temp_name)
            return {
                "schema": PACKINDEX_SCHEMA,
                "mode": "offline_read_only",
                "status": "BLOCK",
                "reason": "output_exists",
                "total_jars": len(jars),
                "resolved_count": len(resolved_files),
                "unresolved_count": 0,
                "unresolved": [],
                "next_step": "輸出檔案已存在，拒絕覆蓋",
            }

        os.replace(temp_name, out_p)

        # Final verification on destination
        with zipfile.ZipFile(out_p, "r") as z_final:
            final_raw = z_final.read("modrinth.index.json")
            if final_raw != index_bytes:
                raise ValueError("final_verification_failed")

    except Exception:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        if out_p.exists():
            try:
                out_p.unlink()
            except OSError:
                pass
        return {
            "schema": PACKINDEX_SCHEMA,
            "mode": "offline_read_only",
            "status": "BLOCK",
            "reason": "write_verification_failed",
            "total_jars": len(jars),
            "resolved_count": len(resolved_files),
            "unresolved_count": 0,
            "unresolved": [],
            "next_step": "寫入驗證失敗，已刪除未完成之檔案",
        }

    return {
        "schema": PACKINDEX_SCHEMA,
        "mode": "offline_read_only",
        "status": "PASS",
        "name": name,
        "version": version,
        "minecraft": minecraft,
        "loader": loader.lower(),
        "side": side,
        "out": out_p.name,
        "total_jars": len(jars),
        "resolved_count": len(resolved_files),
        "unresolved_count": 0,
        "unresolved": [],
        "verified_scope": "local_hashes_and_zip_readback",
        "not_verified": NOT_VERIFIED_CHECKS,
        "next_step": "mrpack 打包完成且讀回驗證通過",
    }


def format_human_packindex(result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    lines = [f"TotemOps .mrpack 打包索引：{status}"]
    if status == "BLOCK":
        lines.append(f"  阻擋原因：{result.get('reason', 'unknown')}")
        lines.append(f"  建議下一步：{result.get('next_step', '請修正阻擋原因後重試')}")
        return "\n".join(lines)

    lines.append(f"  整合包名稱／版本：{result.get('name')} {result.get('version')}")
    lines.append(f"  目標平台：Minecraft {result.get('minecraft')} ({result.get('loader')})")
    lines.append(f"  執行端：{result.get('side')}")
    lines.append(f"  總 JAR 數：{result.get('total_jars', 0)}")
    lines.append(f"  已解析下載來源：{result.get('resolved_count', 0)}")

    unresolved = result.get("unresolved", [])
    if unresolved:
        lines.append(f"  未解析模組清單（{len(unresolved)} 個）：")
        for u in unresolved[:10]:
            lines.append(f"    - {u}")
        if len(unresolved) > 10:
            lines.append(f"    ... 還有 {len(unresolved) - 10} 個模組")

    if status == "PASS":
        lines.append(f"  已寫出 .mrpack 檔案：{result.get('out')}（讀回驗證通過）")

    lines.append(f"  建議下一步：{result.get('next_step', '')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TotemOps Modrinth .mrpack index exporter")
    parser.add_argument("mods_dir", help="Path to mods directory")
    parser.add_argument("--name", required=True, help="Pack name")
    parser.add_argument("--version", required=True, help="Pack version")
    parser.add_argument("--minecraft", required=True, help="Minecraft version")
    parser.add_argument("--loader", required=True, help="Mod loader (neoforge, forge, fabric, quilt)")
    parser.add_argument("--downloads-map", default=None, help="Path to downloads map JSON")
    parser.add_argument("--out", default=None, help="Output .mrpack path")
    parser.add_argument("--side", choices=("both", "client", "server"), default="both")
    parser.add_argument("--json", action="store_true", help="Output JSON object")
    args = parser.parse_args(argv)

    res = build_packindex(
        mods_dir=Path(args.mods_dir),
        name=args.name,
        version=args.version,
        minecraft=args.minecraft,
        loader=args.loader,
        downloads_map_path=Path(args.downloads_map) if args.downloads_map else None,
        out_path=Path(args.out) if args.out else None,
        side=args.side,
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    else:
        print(format_human_packindex(res))

    st = res.get("status")
    return 0 if st == "PASS" else 2 if st == "BLOCK" else 3


if __name__ == "__main__":
    sys.exit(main())
