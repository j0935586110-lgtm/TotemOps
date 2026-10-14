# SPDX-License-Identifier: Apache-2.0
"""Reusable NeoForge loader seed: only libraries/versions plus generated run.sh.

No live-world data, configs, players or mods are copied. Seed is only trusted
after validating version, Docker image identity, file hashes and provenance.
"""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

MAX_ENTRIES = 2000
MAX_TOTAL = 1024 * 1024 * 1024
INCLUDED_DIRS = ("libraries", "versions")
INCLUDED_FILES = ("run.sh", ".neoforge-manifest.json")
SKIP_PARTS = {"world", "world_nether", "world_the_end", "mods", "config",
              "logs", "kubejs", "playerdata", "plugins", "saves"}
SEED_JSON = "totemops-runtime-seed.json"


class SeedRejected(ValueError):
    pass


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_path(path, sandbox_root):
    if path.is_symlink():
        raise SeedRejected("symlink_not_allowed")
    root = sandbox_root.resolve(strict=True)
    dest = path.resolve(strict=False)
    if dest == root or not dest.is_relative_to(root):
        raise SeedRejected("target_outside_authorized_sandbox")
    if any(s.lower() in SKIP_PARTS for s in dest.relative_to(root).parts):
        raise SeedRejected("protected_path")
    return dest


def _inputs(source: Path, game_version: str, version: str):
    # Sources are read-only; never ingest arbitrary directories or whole worlds.
    run = source / "run.sh"
    neo = source / "libraries" / "net" / "neoforged" / "neoforge" / version / "unix_args.txt"
    if not run.is_file() or run.is_symlink() or not neo.is_file() or neo.is_symlink():
        raise SeedRejected("source_not_matching_neoforge_version")
    if f"/neoforge/{version}/unix_args.txt" not in run.read_text(errors="replace"):
        raise SeedRejected("loader_script_version_mismatch")
    installer_manifest = source / ".neoforge-manifest.json"
    if installer_manifest.is_symlink() or not installer_manifest.is_file():
        raise SeedRejected("missing_installer_manifest")
    try:
        installer = json.loads(installer_manifest.read_text(encoding="utf-8"))
        if (installer.get("minecraftVersion"), installer.get("forgeVersion"),
                installer.get("serverEntry")) != (game_version, version, "run.sh"):
            raise SeedRejected("installed_loader_manifest_mismatch")
    except (ValueError, TypeError) as e:
        raise SeedRejected("invalid_installer_manifest") from e
    entries = [run, installer_manifest]
    for folder_name in INCLUDED_DIRS:
        folder = source / folder_name
        if folder.is_symlink():
            raise SeedRejected("symlink_in_source")
        if folder.is_dir():
            entries.extend(p for p in folder.rglob("*") if p.is_file() or p.is_symlink())
    if len(entries) > MAX_ENTRIES:
        raise SeedRejected("seed_too_many_files")
    total = 0
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise SeedRejected("seed_symlink_or_bad_file")
        relative = path.relative_to(source)
        if relative.parts[0] in SKIP_PARTS:
            raise SeedRejected("protected_file_in_seed")
        total += path.stat().st_size
        if total > MAX_TOTAL:
            raise SeedRejected("seed_too_large")
    return sorted(entries, key=lambda x: str(x.relative_to(source))), total


def create_seed(source_data: Path, seed_dir: Path, sandbox_root: Path,
                game_version: str, loader_version: str, image_id: str):
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", game_version) or not re.fullmatch(r"\d+(?:\.\d+){2,3}", loader_version):
        raise SeedRejected("invalid_seed_version")
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", image_id):
        raise SeedRejected("invalid_docker_image_id")
    _safe_path(seed_dir, sandbox_root)
    if seed_dir.exists():
        raise SeedRejected("seed_destination_already_exists")
    entries, total = _inputs(source_data, game_version, loader_version)
    started = time.monotonic()
    copied = []
    try:
        seed_dir.mkdir(parents=True, exist_ok=False)
        for file in entries:
            relative = file.relative_to(source_data)
            dest = seed_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)
            original = _sha(file)
            if _sha(dest) != original:
                raise SeedRejected("seed_copy_hash_mismatch")
            copied.append({"path": relative.as_posix(), "sha256": original,
                           "size": dest.stat().st_size})
        meta = {"schema": 1, "type": "NEOFORGE", "game_version": game_version,
                "loader_version": loader_version, "image_id": image_id,
                "files": copied, "total_bytes": total}
        (seed_dir / SEED_JSON).write_text(json.dumps(meta, sort_keys=True,
                                                     separators=(",", ":"))+"\n")
        return {"status": "SEED_CREATED", "files": len(copied), "bytes": total,
                "elapsed_seconds": round(time.monotonic()-started,3)}
    except Exception:
        shutil.rmtree(seed_dir, ignore_errors=True)
        raise


def prepare_seed(seed_dir: Path, dest_data: Path, sandbox_root: Path,
                 game_version: str, loader_version: str, image_id: str,
                 measured_cold_install_s: float):
    _safe_path(dest_data, sandbox_root)
    if seed_dir.is_symlink() or not seed_dir.is_dir():
        return {"status": "DOWNLOAD", "reason": "no_local_loader_seed"}
    manifest = seed_dir / SEED_JSON
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 250000:
        return {"status": "DOWNLOAD", "reason": "missing_seed_manifest"}
    try:
        meta = json.loads(manifest.read_text())
        if (meta["type"],meta["game_version"],meta["loader_version"],meta["image_id"]) != (
                "NEOFORGE", game_version, loader_version, image_id):
            return {"status": "DOWNLOAD", "reason": "runtime_or_image_version_mismatch"}
        files = meta["files"]
        if not files or len(files) > MAX_ENTRIES:
            raise SeedRejected("seed_bad_entry_count")
        start = time.monotonic()
        total = 0
        source_files = []
        for entry in files:
            path = entry["path"]
            if not isinstance(path,str) or path.startswith("/") or "\\" in path or ".." in Path(path).parts:
                raise SeedRejected("unsafe_seed_path")
            if path not in INCLUDED_FILES and not (path.startswith("libraries/") or path.startswith("versions/")):
                raise SeedRejected("seed_non_loader_file")
            candidate = seed_dir / path
            if candidate.is_symlink() or not candidate.is_file():
                raise SeedRejected("seed_missing_or_symlink")
            if _sha(candidate) != entry["sha256"] or candidate.stat().st_size != entry["size"]:
                raise SeedRejected("seed_hash_mismatch")
            source_files.append((candidate,path))
            total += entry["size"]
        if total > MAX_TOTAL:
            raise SeedRejected("seed_too_large")
        verify_s = time.monotonic()-start
        # Estimate independently copied bytes at twice the measured read cost,
        # not a guess about live network performance.
        copy_estimate_s = verify_s*2 + .2
        if measured_cold_install_s > 0 and copy_estimate_s >= measured_cold_install_s:
            return {"status": "DOWNLOAD", "reason": "measured_download_faster",
                    "estimated_local_s": round(copy_estimate_s,3),
                    "measured_cold_s": measured_cold_install_s}
        if dest_data.exists():
            # The caller may have already staged the verified mod JARs, but no
            # world/config/private files or previous loader installation.
            allowed = {"mods", ".modrinth-manifest.json"}
            existing = {p.name for p in dest_data.iterdir()}
            if not existing.issubset(allowed):
                raise SeedRejected("destination_must_be_empty")
            if (dest_data / "mods").is_symlink():
                raise SeedRejected("destination_symlink")
        dest_data.mkdir(parents=True,exist_ok=True)
        copy_start = time.monotonic()
        for source, path in source_files:
            target = dest_data / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source,target)
            if _sha(target)!=_sha(source):
                raise SeedRejected("prepared_seed_hash_mismatch")
        return {"status": "LOCAL_LOADER_CLONE", "files": len(files), "bytes": total,
                "copy_seconds": round(time.monotonic()-copy_start,3),
                "verify_seconds": round(verify_s,3),
                "estimate_seconds": round(copy_estimate_s,3),
                "cold_reference_seconds": measured_cold_install_s,
                "image_id": image_id, "game_version": game_version,
                "loader_version": loader_version}
    except (KeyError, TypeError, ValueError, OSError) as err:
        raise SeedRejected(str(err)[:100]) from err
