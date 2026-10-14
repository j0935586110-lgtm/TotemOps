# SPDX-License-Identifier: Apache-2.0
"""TotemOps CAS Lite: no daemon, no DB, no links, content-addressed JARs only.

The caller explicitly opts in via a marked disposable sandbox. A receipt
names the exact files and SHA-256 hashes; cached bytes are rehashed on use.
A manifest identifies a *set of files*, but never promises game compatibility.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

SCHEMA = 1
MAX_FILES = 100
MAX_BLOB = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_RECEIPT = 65536
PROTECTED = {"world", "world_nether", "world_the_end", "kubejs", "config",
             "playerdata", "plugins", "saves", "datapacks", "resourcepacks"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9._+-]+\.jar\Z")
CACHE_DIR = ".totemops-cas"


class CASRejected(ValueError):
    pass


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _root(sandbox_root: Path) -> Path:
    if sandbox_root.name != "agy-sandbox" or sandbox_root.is_symlink() or not sandbox_root.is_dir():
        raise CASRejected("sandbox_root_not_allowlisted")
    marker = sandbox_root / ".agy-manager-sandbox"
    if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != b"AGY_TEST_SANDBOX_V1\n":
        raise CASRejected("sandbox_marker_invalid")
    return sandbox_root.resolve(strict=True)


def _path_under(root: Path, item: Path, *, allow_cache: bool = False) -> Path:
    candidate = item.absolute()
    # Verify symlinks before resolving, including all ancestors below sandbox.
    if not candidate.is_relative_to(root) or candidate == root:
        raise CASRejected("path_outside_sandbox")
    relative = candidate.relative_to(root)
    if any(part.lower() in PROTECTED or part.lower().startswith("barian_")
           for part in relative.parts):
        raise CASRejected("protected_path")
    if not allow_cache and CACHE_DIR in relative.parts:
        raise CASRejected("cas_is_not_a_user_source_or_target")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise CASRejected("symlink_path")
    if not candidate.resolve(strict=False).is_relative_to(root):
        raise CASRejected("resolved_path_outside_sandbox")
    return candidate


def _parse_receipt(receipt: dict) -> tuple[list[dict], dict]:
    if not isinstance(receipt, dict) or receipt.get("status") != "STAGED_ONLY":
        raise CASRejected("stage_receipt_required")
    raw = receipt.get("staged_jars")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_FILES:
        raise CASRejected("invalid_stage_file_count")
    files = []
    seen = set()
    for x in raw:
        if not isinstance(x, dict):
            raise CASRejected("invalid_stage_entry")
        name, digest = x.get("name"), x.get("sha256")
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or name in {".", ".."} or name in seen
                or not isinstance(digest, str) or not HASH.fullmatch(digest)):
            raise CASRejected("invalid_stage_name_or_hash")
        seen.add(name)
        files.append({"name": name, "sha256": digest})
    candidate = receipt.get("candidate", {})
    if not isinstance(candidate, dict):
        raise CASRejected("invalid_candidate")
    # Whitelist metadata fields. Never persist tokens, log lines or local paths.
    meta = {}
    for key in ("project", "version_id", "game_version", "loader"):
        val = candidate.get(key)
        if val is not None:
            if not isinstance(val, str) or len(val) > 80 or not re.fullmatch(r"[A-Za-z0-9_.-]+", val):
                raise CASRejected("invalid_candidate_metadata")
            meta[key] = val
    return sorted(files, key=lambda f: f["name"]), meta


def _identity(files: list[dict], candidate: dict) -> tuple[str, bytes]:
    doc = {"schema": SCHEMA, "files": files, "candidate": candidate}
    content = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest(), content


def _checked_cache_parts(root: Path, *parts: str) -> Path:
    """Refuse symlinked CAS parent folders, not just linked individual blobs."""
    p = root
    for part in (CACHE_DIR, *parts):
        p = p / part
        if p.is_symlink():
            raise CASRejected("cas_parent_symlink")
    return p


def _locations(root: Path, digest: str) -> Path:
    if not HASH.fullmatch(digest):
        raise CASRejected("invalid_content_hash")
    return _checked_cache_parts(root, "objects", "sha256", digest[:2]) / digest


def _manifest_path(root: Path, identity: str) -> Path:
    if not HASH.fullmatch(identity):
        raise CASRejected("invalid_manifest_hash")
    return _checked_cache_parts(root, "manifests") / (identity + ".json")


def _atomic_verified_copy(source: Path, target: Path, expected: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise CASRejected("target_symlink")
    fd, pending = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
    tmp = Path(pending)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(chunk)
                if total > MAX_BLOB:
                    raise CASRejected("artifact_too_large")
                digest.update(chunk)
                out.write(chunk)
        if total <= 0 or digest.hexdigest() != expected:
            raise CASRejected("artifact_hash_mismatch")
        if target.is_symlink():
            raise CASRejected("target_symlink")
        os.replace(tmp, target)
        return total
    finally:
        tmp.unlink(missing_ok=True)


def _validated_manifest(root: Path, receipt: dict) -> tuple[list[dict], str]:
    files, candidate = _parse_receipt(receipt)
    mid, original = _identity(files, candidate)
    path = _manifest_path(root, mid)
    if path.is_symlink():
        raise CASRejected("manifest_symlink")
    if not path.is_file():
        raise FileNotFoundError("cas_manifest_missing")
    if path.stat().st_size > MAX_RECEIPT or path.read_bytes() != original:
        raise CASRejected("cas_manifest_invalid")
    return files, mid


def import_receipt(sandbox_root: Path, source_dir: Path, receipt: dict) -> dict:
    start = time.monotonic()
    root = _root(sandbox_root)
    source = _path_under(root, source_dir)
    if not source.is_dir():
        raise CASRejected("source_not_directory")
    files, candidate = _parse_receipt(receipt)
    total = 0
    ingested, reused = 0, 0
    for entry in files:
        src = _path_under(root, source / entry["name"])
        if not src.is_file() or src.is_symlink():
            raise CASRejected("source_file_missing_or_symlink")
        size = src.stat().st_size
        if not 0 < size <= MAX_BLOB or total + size > MAX_TOTAL:
            raise CASRejected("source_size_limit")
        total += size
        # Verify before deciding to copy. Existing objects are reverified.
        if _hash_file(src) != entry["sha256"]:
            raise CASRejected("source_sha256_mismatch")
        target = _locations(root, entry["sha256"])
        if target.is_symlink():
            raise CASRejected("blob_symlink")
        if target.exists():
            if not target.is_file() or _hash_file(target) != entry["sha256"]:
                raise CASRejected("corrupt_existing_cas_blob")
            reused += 1
        else:
            _atomic_verified_copy(src, target, entry["sha256"])
            ingested += 1
    mid, manifest_bytes = _identity(files, candidate)
    mf = _manifest_path(root, mid)
    if mf.is_symlink():
        raise CASRejected("manifest_symlink")
    if mf.is_file():
        if mf.read_bytes() != manifest_bytes:
            raise CASRejected("manifest_hash_collision")
    else:
        mf.parent.mkdir(parents=True, exist_ok=True)
        fd, pending = tempfile.mkstemp(prefix=".pending-", dir=mf.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(manifest_bytes)
            os.replace(pending, mf)
        finally:
            Path(pending).unlink(missing_ok=True)
    return {"status": "CAS_IMPORTED", "manifest_sha256": mid,
            "artifacts": len(files), "new_blobs": ingested, "existing_blobs": reused,
            "logical_bytes": total, "seconds": round(time.monotonic()-start, 4)}


def verify_receipt(sandbox_root: Path, receipt: dict) -> dict:
    start = time.monotonic()
    root = _root(sandbox_root)
    try:
        files, mid = _validated_manifest(root, receipt)
    except FileNotFoundError:
        return {"status": "MISS", "reason": "cas_manifest_missing"}
    total = 0
    for item in files:
        blob = _locations(root, item["sha256"])
        if blob.is_symlink():
            raise CASRejected("cas_blob_symlink")
        if not blob.is_file():
            return {"status": "MISS", "reason": "cas_blob_missing"}
        size = blob.stat().st_size
        if size > MAX_BLOB or size <= 0 or total + size > MAX_TOTAL:
            raise CASRejected("cas_blob_size_limit")
        if _hash_file(blob) != item["sha256"]:
            raise CASRejected("cas_blob_corrupt")
        total += size
    return {"status": "CAS_VALID", "manifest_sha256": mid,
            "artifacts": len(files), "bytes": total,
            "verification_seconds": round(time.monotonic()-start, 4)}


def restore_receipt(sandbox_root: Path, destination: Path, receipt: dict,
                    previous_download_seconds: float | None = None) -> dict:
    start = time.monotonic()
    root = _root(sandbox_root)
    target = _path_under(root, destination)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise CASRejected("destination_not_empty")
    verified = verify_receipt(root, receipt)
    if verified["status"] != "CAS_VALID":
        return verified
    files, mid = _validated_manifest(root, receipt)
    # Two reads/copies cost similar to a verified local re-use, measured,
    # not a claim of a universal download speed advantage.
    estimate = max(.05, verified["verification_seconds"] * 2 + .05)
    if (type(previous_download_seconds) in (float, int)
            and previous_download_seconds > 0 and estimate >= previous_download_seconds):
        return {"status": "DOWNLOAD", "reason": "measured_download_preferred",
                "estimated_restore_seconds": round(estimate, 4),
                "prior_download_seconds": previous_download_seconds}
    target.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for item in files:
            dest = target / item["name"]
            _atomic_verified_copy(_locations(root, item["sha256"]), dest, item["sha256"])
            written.append(dest)
    except Exception:
        for dest in written:
            dest.unlink(missing_ok=True)
        raise
    return {"status": "CAS_RESTORED", "manifest_sha256": mid,
            "artifacts": len(files), "bytes": verified["bytes"],
            "estimated_restore_seconds": round(estimate, 4),
            "seconds": round(time.monotonic()-start, 4)}


def stats(sandbox_root: Path) -> dict:
    root = _root(sandbox_root)
    objects = _checked_cache_parts(root, "objects", "sha256")
    manifests = _checked_cache_parts(root, "manifests")
    physical, count, pack_count, logical = 0, 0, 0, 0
    if objects.exists():
        for folder in objects.iterdir():
            if folder.is_symlink() or not folder.is_dir():
                raise CASRejected("cas_invalid_object_bucket")
            for item in folder.iterdir():
                if item.is_symlink() or not item.is_file():
                    raise CASRejected("cas_invalid_object_entry")
                count += 1
                if count > 10000:
                    raise CASRejected("cas_stats_entry_limit")
                physical += item.stat().st_size
    if manifests.exists():
        for item in manifests.iterdir():
            if item.is_symlink() or not item.is_file() or item.stat().st_size > MAX_RECEIPT:
                raise CASRejected("cas_invalid_manifest_entry")
            pack_count += 1
            if pack_count > 10000:
                raise CASRejected("cas_stats_entry_limit")
            for f in json.loads(item.read_text())["files"]:
                blob = _locations(root, f["sha256"])
                if blob.is_file():
                    logical += blob.stat().st_size
    return {"status": "PASS", "blobs": count, "stored_bytes": physical,
            "manifests": pack_count, "referenced_bytes": logical,
            "deduplicated_bytes": max(0, logical - physical)}
