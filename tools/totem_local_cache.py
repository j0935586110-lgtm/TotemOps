# SPDX-License-Identifier: Apache-2.0
"""Deterministic, bounded, local-only JAR artifact reuse for TotemOps.

Reads and clones verified JARs from an explicitly supplied sandbox subfolder.
Never uses hardlinks or copies worlds/config; only compares names + SHA-256.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path


PROTECTED = {"world", "world_nether", "world_the_end", "config", "kubejs",
             "playerdata", "datapacks", "plugins", "saves", "resourcepacks"}


class LocalCacheRejected(ValueError):
    pass


def discover_verified_cache(sandbox_root: Path, expected_hashes: dict[str, str],
                            max_directories: int = 80, max_depth: int = 5) -> Path | None:
    """Bounded discovery strictly inside an owner-marked disposable sandbox.

    Folder discovery checks only filenames; clone_if_faster verifies full SHA-256
    before any candidate can be reused.
    """
    if not expected_hashes or not sandbox_root.is_dir() or sandbox_root.is_symlink():
        return None
    queue = [(sandbox_root, 0)]
    visited = 0
    needed = set(expected_hashes)
    while queue and visited < max_directories:
        folder, depth = queue.pop(0)
        if folder.is_symlink():
            continue
        visited += 1
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        filenames = {p.name for p in children if p.is_file() and not p.is_symlink()}
        if folder != sandbox_root and needed.issubset(filenames):
            return folder
        if depth < max_depth:
            queue.extend((p, depth + 1) for p in children
                         if p.is_dir() and not p.is_symlink()
                         and p.name.lower() not in PROTECTED
                         and not p.name.lower().startswith("barian_"))
    return None


def clone_if_faster(source: Path, sandbox_root: Path, destination: Path,
                    expected_hashes: dict[str, str], previous_download_seconds: float | None) -> dict:
    """Compare measured local checksum+copy cost with last *observed* download time.

    Returns a small report; only writes to the disposable destination when local
    validation beats previous download. Caller owns lifecycle/cleanup.
    """
    if not expected_hashes or len(expected_hashes) > 100:
        raise LocalCacheRejected("missing_or_unbounded_manifest")
    if source.is_symlink() or not source.is_dir():
        raise LocalCacheRejected("cache_source_not_regular_dir")
    root = sandbox_root.resolve(strict=True)
    selected = source.resolve(strict=True)
    if selected == root or not selected.is_relative_to(root):
        raise LocalCacheRejected("cache_source_outside_sandbox")
    if any(x.lower() in PROTECTED or x.lower().startswith("barian_") for x in selected.parts):
        raise LocalCacheRejected("cache_source_protected")
    for parent in (source, *source.parents):
        if parent == sandbox_root:
            break
        if parent.is_symlink():
            raise LocalCacheRejected("cache_source_symlink")
    entries = []
    total_bytes = 0
    t0 = time.monotonic()
    for filename, expected in sorted(expected_hashes.items()):
        if not (isinstance(filename, str) and filename == Path(filename).name and
                re.fullmatch(r"[a-zA-Z0-9._+-]+\.jar", filename) and
                isinstance(expected, str) and re.fullmatch(r"[a-f0-9]{64}", expected)):
            raise LocalCacheRejected("invalid_cached_filename_or_hash")
        file = source / filename
        if file.is_symlink() or not file.is_file():
            return {"decision": "DOWNLOAD", "reason": "missing_cache_file", "filename": filename}
        size = file.stat().st_size
        if size <= 0 or size > 256 * 1024 * 1024:
            raise LocalCacheRejected("cache_file_size_outside_limits")
        h = hashlib.sha256()
        with file.open("rb") as f:
            for buf in iter(lambda: f.read(1024 * 1024), b""):
                h.update(buf)
        if h.hexdigest() != expected:
            raise LocalCacheRejected("local_cache_artifact_hash_mismatch")
        entries.append((file, filename))
        total_bytes += size
    verify_sec = time.monotonic() - t0
    # Avoid pretending to predict live internet; compare to *measured* last download.
    # Verification is also required on downloaded files; estimate copying costs at
    # twice the observed local read time, with fixed allowance for filesystem writes.
    forecast_sec = max(0.05, 2 * verify_sec + 0.05)
    past = previous_download_seconds
    if (isinstance(past, (int, float)) and not isinstance(past, bool)
            and past > 0 and forecast_sec >= past):
        return {"decision": "DOWNLOAD", "reason": "historical_download_faster",
                "estimated_copy_seconds": round(forecast_sec, 3),
                "previous_download_seconds": past, "cache_verified": True}
    destination.mkdir(parents=True, exist_ok=True)
    tcopy = time.monotonic()
    for original, name in entries:
        # Always independent copy, never hardlink to mutable source files.
        copied = destination / name
        shutil.copy2(original, copied, follow_symlinks=False)
        verify = hashlib.sha256()
        with copied.open("rb") as f:
            for buf in iter(lambda: f.read(1024 * 1024), b""):
                verify.update(buf)
        if verify.hexdigest() != expected_hashes[name]:
            raise LocalCacheRejected("local_cache_copy_integrity_failure")
    return {"decision": "LOCAL_COPY", "cache_verified": True,
            "copied_files": len(entries), "copied_bytes": total_bytes,
            "source_verification_seconds": round(verify_sec, 4),
            "estimated_copy_seconds": round(forecast_sec, 4),
            "actual_copy_seconds": round(time.monotonic() - tcopy, 4),
            "previous_download_seconds": past}
