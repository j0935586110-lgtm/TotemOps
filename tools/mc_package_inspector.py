#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only, bounded Minecraft package inventory and log evidence extractor.

No Java execution, archive extraction, network calls, installation, or LLM guessing.
Supports Forge/NeoForge TOML, Fabric/Quilt JSON, Bukkit/Paper YAML, and .mrpack.
The local dependency graph is *not* a complete Modrinth/Maven resolver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 20000
MAX_UNCOMPRESSED_SUM = 1_000_000_000
MAX_METADATA_BYTES = 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_FOLDER_FILES = 300

META_NAMES = (
    "META-INF/neoforge.mods.toml", "META-INF/mods.toml",
    "fabric.mod.json", "quilt.mod.json", "plugin.yml",
    "paper-plugin.yml", "modrinth.index.json", "manifest.json",
)
ENGINE_IDS = {"minecraft", "forge", "neoforge", "java", "fabricloader", "quilt_loader"}


class InputBlocked(ValueError):
    pass


def _bounded_file(path: Path, max_size: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise InputBlocked("non_regular_or_symlink_file")
    if path.stat().st_size > max_size:
        raise InputBlocked("file_size_limit")


def _hashes(path: Path) -> dict:
    # sha1/sha512 are used as Modrinth file lookup IDs; sha256 is integrity evidence.
    digests = {name: hashlib.new(name) for name in ("sha256", "sha512", "sha1")}
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            for digest in digests.values():
                digest.update(chunk)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _sha256(path: Path) -> str:
    return _hashes(path)["sha256"]


def _read_zipped(z: zipfile.ZipFile, name: str) -> str:
    info = z.getinfo(name)
    if info.file_size > MAX_METADATA_BYTES:
        raise InputBlocked("metadata_too_large")
    if info.file_size > max(1000, info.compress_size * 1000):
        raise InputBlocked("metadata_zip_ratio")
    with z.open(info) as f:
        data = f.read(MAX_METADATA_BYTES + 1)
    if len(data) > MAX_METADATA_BYTES:
        raise InputBlocked("metadata_too_large")
    return data.decode("utf-8-sig")


def _dep(modid, dep, kind):
    if not isinstance(dep, dict):
        raise InputBlocked("invalid_dependency")
    target = str(dep.get("modId") or dep.get("id") or "").strip()
    if not target:
        return None
    if kind == "forge":
        category = "required" if dep.get("mandatory") is True else "optional"
    else:
        category = str(dep.get("type", "required")).lower()
    if category not in {"required", "optional", "incompatible", "discouraged", "embedded"}:
        category = "unknown"
    return {
        "from": modid, "to": target, "type": category,
        "version_range": str(dep.get("versionRange", "")),
        "side": str(dep.get("side", "BOTH")),
    }


def _from_toml(raw, kind):
    obj = tomllib.loads(raw)
    mods = obj.get("mods") or []
    if not isinstance(mods, list) or not mods:
        raise InputBlocked("missing_mods_section")
    result, edges = [], []
    for m in mods:
        if not isinstance(m, dict) or not m.get("modId"):
            raise InputBlocked("missing_mod_id")
        modid = str(m["modId"])
        result.append({"id": modid, "name": m.get("displayName") or modid,
                       "version": str(m.get("version", "UNKNOWN")), "loader": kind})
        d = obj.get("dependencies", {}).get(modid, [])
        for item in d:
            edge = _dep(modid, item, kind)
            if edge:
                edges.append(edge)
    return result, edges


def _fabric(raw, kind):
    obj = json.loads(raw)
    if kind == "quilt":
        obj = obj.get("quilt_loader", {})
        modid = str(obj.get("id", "")).strip()
        dep_fields = [("depends", "required"), ("breaks", "incompatible")]
        meta = obj.get("metadata", {}) or {}
        version = obj.get("version", "UNKNOWN")
        title = meta.get("name", modid)
    else:
        modid = str(obj.get("id", "")).strip()
        dep_fields = [("depends", "required"), ("recommends", "optional"),
                      ("suggests", "optional"), ("breaks", "incompatible"),
                      ("conflicts", "incompatible")]
        title = obj.get("name", modid)
        version = obj.get("version", "UNKNOWN")
    if not modid:
        raise InputBlocked("missing_mod_id")
    edges = []
    for field, category in dep_fields:
        dependencies = obj.get(field) or {}
        if isinstance(dependencies, dict):
            for target, spec in dependencies.items():
                edges.append({"from": modid, "to": str(target), "type": category,
                              "version_range": str(spec), "side": "UNKNOWN"})
        elif isinstance(dependencies, list) and kind == "quilt":
            for spec in dependencies:
                # Quilt lists may contain alternatives; do not invent a winner.
                if isinstance(spec, dict) and isinstance(spec.get("id"), str):
                    edges.append({"from": modid, "to": spec["id"], "type": category,
                                  "version_range": str(spec.get("versions", "")),
                                  "side": "UNKNOWN"})
                else:
                    edges.append({"from": modid, "to": "UNKNOWN", "type": "unknown",
                                  "version_range": "", "side": "UNKNOWN"})
        else:
            raise InputBlocked("unsupported_dependency_format")
    return [{"id": modid, "name": title, "version": str(version), "loader": kind}], edges


def _yaml_plugin(raw, kind):
    if yaml is None:
        raise InputBlocked("pyyaml_missing")
    obj = yaml.safe_load(raw)
    if not isinstance(obj, dict) or not obj.get("name"):
        raise InputBlocked("invalid_plugin_yml")
    name = str(obj["name"])
    edges = []
    if kind == "paper":
        dependencies = obj.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise InputBlocked("invalid_paper_dependencies")
        for section in ("bootstrap", "server"):
            for target, config in (dependencies.get(section) or {}).items():
                if not isinstance(config, dict):
                    raise InputBlocked("invalid_paper_dependency")
                edges.append({"from": name, "to": str(target),
                              "type": "required" if config.get("required", True) else "optional",
                              "version_range": "", "side": "SERVER"})
    else:
        for field, category in (("depend", "required"), ("softdepend", "optional")):
            deps = obj.get(field) or []
            if not isinstance(deps, list):
                raise InputBlocked("invalid_plugin_dependencies")
            for target in deps:
                edges.append({"from": name, "to": str(target), "type": category,
                              "version_range": "", "side": "SERVER"})
    return [{"id": name, "name": name, "version": str(obj.get("version", "UNKNOWN")),
             "loader": kind}], edges


def _mrpack(raw):
    obj = json.loads(raw)
    if obj.get("formatVersion") != 1 or not isinstance(obj.get("files"), list):
        raise InputBlocked("unsupported_mrpack_format")
    deps = obj.get("dependencies") or {}
    if not isinstance(deps, dict):
        raise InputBlocked("invalid_pack_dependencies")
    entries = []
    for file in obj["files"]:
        if not isinstance(file, dict) or not file.get("path"):
            raise InputBlocked("invalid_pack_file")
        member_path = str(file["path"])
        if (member_path.startswith("/") or "\\" in member_path or
                ".." in member_path.split("/") or ":" in member_path.split("/")[0]):
            raise InputBlocked("unsafe_pack_manifest_path")
        entries.append({"path": member_path, "env": file.get("env") or {},
                        "sha512": (file.get("hashes") or {}).get("sha512"),
                        "source": "pack_manifest"})
    return {"name": obj.get("name"), "version": obj.get("versionId"),
            "loader_versions": deps, "files": entries[:MAX_FOLDER_FILES],
            "files_count": len(entries), "truncated": len(entries) > MAX_FOLDER_FILES}



def _curseforge(raw: str) -> dict:
    """Inspect CurseForge v1 pack metadata, never resolve/download JARs."""
    obj = json.loads(raw)
    if (not isinstance(obj, dict) or obj.get("manifestType") != "minecraftModpack"
            or type(obj.get("manifestVersion")) is not int
            or obj["manifestVersion"] != 1):
        raise InputBlocked("unsupported_curseforge_manifest")
    game = obj.get("minecraft")
    files = obj.get("files")
    if (not isinstance(game, dict) or not isinstance(game.get("version"), str)
            or not game["version"] or not isinstance(game.get("modLoaders"), list)
            or not isinstance(files, list) or len(files) > MAX_MEMBERS):
        raise InputBlocked("invalid_curseforge_manifest")
    mod_loaders = []
    for item in game["modLoaders"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise InputBlocked("invalid_curseforge_modloader")
        mod_loaders.append(item["id"][:120])
    overrides = obj.get("overrides", "overrides")
    if (not isinstance(overrides, str) or not overrides
            or overrides.startswith("/") or "\\" in overrides
            or ":" in overrides.split("/")[0]
            or ".." in overrides.split("/")):
        raise InputBlocked("unsafe_curseforge_overrides")
    required = optional = 0
    for file in files:
        if (not isinstance(file, dict)
                or type(file.get("projectID")) is not int or file["projectID"] <= 0
                or type(file.get("fileID")) is not int or file["fileID"] <= 0
                or type(file.get("required")) is not bool):
            raise InputBlocked("invalid_curseforge_file_reference")
        if file["required"]:
            required += 1
        else:
            optional += 1
    return {
        "format": "curseforge", "name": obj.get("name", ""),
        "version": str(obj.get("version", "")),
        "minecraft": game["version"], "mod_loaders": mod_loaders,
        "files_count": len(files), "required_files": required,
        "optional_files": optional, "overrides": overrides,
        "external_files_require_launcher_download": bool(files),
        "game_test_executed": False,
        "checks_not_run": ["external_file_resolution", "client_install", "game_start"],
    }

def inspect_one(path: Path) -> dict:
    _bounded_file(path, MAX_ARCHIVE_BYTES)
    if path.suffix.lower() not in {".jar", ".zip", ".mrpack"}:
        raise InputBlocked("unsupported_extension")
    hashes = _hashes(path)
    record = {"file": path.name, "sha256": hashes["sha256"], "hashes": hashes,
              "size": path.stat().st_size, "mods": [], "dependencies": [],
              "pack": None, "metadata_found": [], "warnings": [],
              "maintenance": {"status": "UNKNOWN", "reason": "no_official_online_verification"}}
    try:
        with zipfile.ZipFile(path, "r") as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS:
                raise InputBlocked("archive_member_limit")
            if sum(x.file_size for x in infos) > MAX_UNCOMPRESSED_SUM:
                raise InputBlocked("archive_uncompressed_size_limit")
            names = set(z.namelist())
            matches = [m for m in META_NAMES if m in names]
            record["metadata_found"] = matches
            if not matches:
                record["warnings"].append("no_supported_metadata")
            for name in matches:
                raw = _read_zipped(z, name)
                if name.endswith(".toml") and name in META_NAMES[:2]:
                    kind = "neoforge" if "neoforge." in name else "forge"
                    mods, deps = _from_toml(raw, kind)
                elif name in ("fabric.mod.json", "quilt.mod.json"):
                    kind = "fabric" if name.startswith("fabric") else "quilt"
                    mods, deps = _fabric(raw, kind)
                elif name in ("plugin.yml", "paper-plugin.yml"):
                    mods, deps = _yaml_plugin(raw, "paper" if name.startswith("paper") else "bukkit")
                elif name == "modrinth.index.json":
                    record["pack"] = _mrpack(raw)
                    continue
                elif name == "manifest.json":
                    record["pack"] = _curseforge(raw)
                    if record["pack"]["external_files_require_launcher_download"]:
                        record["warnings"].append("curseforge_external_files_not_resolved")
                    continue
                else:
                    record["warnings"].append("unsupported_metadata")
                    continue
                record["mods"].extend(mods)
                record["dependencies"].extend(deps)
    except (zipfile.BadZipFile, UnicodeError, tomllib.TOMLDecodeError,
            json.JSONDecodeError, yaml.YAMLError if yaml is not None else ValueError) as exc:
        raise InputBlocked("invalid_archive_or_metadata") from exc
    return record


def inspect_path(path: Path):
    if path.is_symlink():
        raise InputBlocked("symlink_not_allowed")
    paths = [path] if path.is_file() else []
    if path.is_dir():
        paths = sorted(
            (p for p in path.iterdir() if p.suffix.lower() in {".jar", ".mrpack", ".zip"}),
            key=lambda p: p.name,
        )
        if len(paths) > MAX_FOLDER_FILES:
            raise InputBlocked("too_many_packages")
    if not paths:
        raise InputBlocked("no_supported_packages")
    outputs, rejected = [], []
    for p in paths:
        try:
            outputs.append(inspect_one(p))
        except (InputBlocked, OSError, ValueError, TypeError) as e:
            rejected.append({"file": p.name, "reason": str(e)[:120]})
    index = {}
    for f in outputs:
        for m in f["mods"]:
            index.setdefault(m["id"].lower(), []).append(f["file"])
    findings = []
    for mod, files in index.items():
        if len(files) > 1:
            findings.append({"kind": "duplicate_mod_id", "id": mod, "files": files,
                             "severity": "conflict", "evidence": "local_jar_metadata"})
    loader_types = {m["loader"] for f in outputs for m in f["mods"]}
    game_mod_loaders = loader_types & {"forge", "neoforge", "fabric", "quilt"}
    if len(game_mod_loaders) > 1:
        findings.append({"kind": "mixed_mod_loaders", "severity": "review",
                         "loaders": sorted(game_mod_loaders), "evidence": "local_jar_metadata",
                         "note": "without one selected server target compatibility remains unknown"})
    for file in outputs:
        suffix = re.search(r"[-_]((?:v)?[0-9]+(?:\.[0-9]+){1,4})$", Path(file["file"]).stem)
        if not suffix:
            continue
        named_version = suffix.group(1).lstrip("v")
        for mod in file["mods"]:
            embedded_version = mod["version"].lstrip("v")
            if (re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", embedded_version)
                    and embedded_version != named_version):
                findings.append({"kind": "filename_metadata_version_mismatch_candidate",
                                 "severity": "review", "file": file["file"], "mod_id": mod["id"],
                                 "filename_version": named_version,
                                 "declared_version": embedded_version,
                                 "evidence": "release_filename_and_local_jar_metadata",
                                 "note": "review naming rules, not proof of a bug"})
    edges = [x for f in outputs for x in f["dependencies"]]
    for edge in edges:
        target = edge["to"].lower()
        if edge["type"] == "incompatible" and target in index:
            findings.append({"kind": "declared_incompatible", "source": edge["from"],
                             "target": edge["to"], "severity": "conflict",
                             "evidence": "local_mod_metadata"})
        if edge["type"] == "required" and target not in index and target not in ENGINE_IDS:
            findings.append({"kind": "required_not_in_supplied_set", "source": edge["from"],
                             "target": edge["to"], "severity": "review",
                             "evidence": "local_mod_metadata",
                             "note": "not proof dependency is absent from installed server"})
    incomplete = bool(rejected) or any(p["warnings"] for p in outputs)
    return {
        "status": "BLOCK" if not outputs else "PARTIAL" if incomplete else "PASS",
        "mode": "offline_read_only", "files_analyzed": len(outputs),
        "files_rejected": rejected, "packages": outputs, "findings": findings,
        "checks_not_run": ["remote_version_compatibility", "game_runtime_test",
                           "online_project_maintenance", "Maven_range_solver"],
    }


PATTERNS = [
    ("client_class_on_server", re.compile(r"(?:NoClassDefFoundError|ClassNotFoundException):?\s*net[./]minecraft[./]client[./][A-Za-z0-9_$./]+"), "review"),
    ("invalid_dedicated_server_dist", re.compile(r"(?:invalid dist DEDICATED_SERVER|Attempted to load class [^\n]{0,150} for invalid dist)", re.I), "review"),
    ("java_runtime_version_mismatch", re.compile(r"(?:UnsupportedClassVersionError|class file version\s+\d+(?:\.\d+)?[^\n]{0,160}(?:runtime|recognizes))", re.I), "review"),
    ("mixin_injection_failure", re.compile(r"(?:MixinApplyError|MixinTransformerError|Critical injection failure)", re.I), "review"),
    ("loader_version_incompatible", re.compile(r"(?:Incompatible mods found!|incompatible mod loader|unsupported mod loader)", re.I), "review"),
    ("missing_class", re.compile(r"(?:NoClassDefFoundError|ClassNotFoundException):?\s*([^\s]+)"), "review"),
    ("dependency_load_failure", re.compile(r"(?:missing or unsupported mandatory dependencies|Missing mandatory dependencies)", re.I), "review"),
    ("out_of_memory", re.compile(r"(?:OutOfMemoryError|Java heap space)", re.I), "review"),
    ("mod_exception", re.compile(r"(?:Mod [A-Za-z0-9_.-]+ encountered an error|Failed to load mod .*\.jar)", re.I), "review"),
]


def inspect_log(path: Path) -> dict:
    _bounded_file(path, MAX_LOG_BYTES)
    findings = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            for kind, pattern, severity in PATTERNS:
                found = pattern.search(line)
                if found:
                    # Avoid surfacing arbitrary log text (IP, tokens, passwords).
                    findings.append({"line": n, "kind": kind, "severity": severity,
                                     "match": found.group(0)[:120],
                                     "assessment": "clue_not_confirmed_root_cause"})
                    break
            if len(findings) >= 80:
                break
    return {"status": "PASS", "mode": "offline_read_only", "file_sha256": _sha256(path),
            "signals": findings, "confirmed_faulty_mod": None,
            "next_step": "compare with installed mods, load ordering and recent changes"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="task", required=True)
    for cmd in ("inspect", "diagnose"):
        sp = sub.add_parser(cmd)
        sp.add_argument("path")
    args = parser.parse_args(argv)
    try:
        data = inspect_path(Path(args.path)) if args.task == "inspect" else inspect_log(Path(args.path))
    except (InputBlocked, OSError, ValueError) as e:
        print(json.dumps({"status": "BLOCK", "reason": str(e)[:160],
                          "mode": "offline_read_only"}))
        return 2
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 0 if data["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
