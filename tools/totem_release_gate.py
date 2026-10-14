#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only signed release compatibility gate for existing Minecraft launchers.

This is NOT a downloader, installer, executable updater or continuous monitor.
Owner-reviewed releases are signed offline; trusted launcher checks a pinned
public key before deciding whether the *existing* mod sync hook may run.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

MAX_RELEASE_SIZE = 65536
MAX_SIGNATURE_SIZE = 1024
MAX_PUBLIC_KEY_SIZE = 4096
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
VERSION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,63}$")


class ReleaseBlocked(ValueError):
    pass


def _load_bytes(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ReleaseBlocked("missing_or_oversized_file")
    return path.read_bytes()


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, val in pairs:
        if key in out:
            raise ReleaseBlocked("duplicate_json_key")
        out[key] = val
    return out


def _check_release(data: object, *, expected_profile: str, allowed_host: str) -> dict:
    if not isinstance(data, dict) or set(data) != {
        "schema", "profile", "sequence", "minecraft", "loader",
        "loader_version", "java_major", "updater_contract", "sync_feed"
    }:
        raise ReleaseBlocked("release_schema_mismatch")
    if data["schema"] != 1 or isinstance(data["schema"], bool):
        raise ReleaseBlocked("unknown_schema")
    if not isinstance(data["profile"], str) or not ID.fullmatch(data["profile"]):
        raise ReleaseBlocked("invalid_profile")
    if data["profile"] != expected_profile:
        raise ReleaseBlocked("unexpected_profile")
    if type(data["sequence"]) is not int or not 1 <= data["sequence"] <= 2**53:
        raise ReleaseBlocked("invalid_sequence")
    mc = data["minecraft"]
    if not isinstance(mc, str) or not re.fullmatch(r"1\.\d{1,3}(?:\.\d{1,3})?", mc):
        raise ReleaseBlocked("invalid_minecraft_version")
    if data["loader"] not in ("forge", "neoforge", "fabric", "quilt"):
        raise ReleaseBlocked("invalid_loader")
    for key in ("loader_version", "updater_contract"):
        value = data[key]
        if not isinstance(value, str) or not VERSION.fullmatch(value):
            raise ReleaseBlocked("invalid_" + key)
    if type(data["java_major"]) is not int or data["java_major"] not in (8, 16, 17, 21, 25):
        raise ReleaseBlocked("unsupported_java_major")
    parts_of_version = tuple(map(int, mc.split(".")))
    # Minecraft 1.20.5+ (and 1.21+) explicitly require Java 21.
    if len(parts_of_version) >= 2 and (
        parts_of_version[1] > 20 or
        (parts_of_version[1] == 20 and len(parts_of_version) > 2 and parts_of_version[2] >= 5)
    ) and data["java_major"] < 21:
        raise ReleaseBlocked("java_too_old_for_minecraft")
    # Minecraft 1.18-1.20.4: Java 17 baseline; a newer supported Java
    # still needs independent mod/loader runtime tests.
    if 18 <= parts_of_version[1] <= 20 and data["java_major"] < 17:
        raise ReleaseBlocked("java_too_old_for_minecraft")
    url = data["sync_feed"]
    if not isinstance(url, str) or len(url) > 1024 or any(c.isspace() for c in url):
        raise ReleaseBlocked("invalid_sync_feed")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (parts.scheme != "https" or not host or host.lower() != allowed_host.lower()
                or parts.username or parts.password or parts.port not in (None, 443)
                or parts.fragment or not parts.path.startswith("/")
                or "\\" in parts.path or any(segment in (".", "..") for segment in parts.path.split("/"))):
            raise ReleaseBlocked("untrusted_sync_feed")
    except ValueError as exc:
        raise ReleaseBlocked("untrusted_sync_feed") from exc
    return data


def _verify_release(
    source: Path, signature: Path, public_key: Ed25519PublicKey,
    *, expected_profile: str, allowed_host: str
) -> dict:
    raw = _load_bytes(source, MAX_RELEASE_SIZE)
    sig_b64 = _load_bytes(signature, MAX_SIGNATURE_SIZE).strip()
    try:
        sig = base64.b64decode(sig_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ReleaseBlocked("invalid_signature_encoding") from exc
    if len(sig) != 64:
        raise ReleaseBlocked("invalid_signature_length")
    try:
        public_key.verify(sig, raw)
    except InvalidSignature as exc:
        raise ReleaseBlocked("invalid_owner_signature") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBlocked("invalid_release_json") from exc
    return _check_release(decoded, expected_profile=expected_profile, allowed_host=allowed_host)


def decide(installed: dict | None, incoming: dict) -> dict:
    """No state writes and no execution; returned action is advisory only."""
    result = {
        "status": "REVIEW_REQUIRED",
        "action": "MANUAL_FIRST_INSTALL" if installed is None else "NO_ACTION",
        "reason": "first_install_needs_verified_launcher" if installed is None else "unknown",
        "signature_verified": True,
        "write_performed": False,
        "download_performed": False,
        "game_launched": False,
        "server_contacted": False,
    }
    if installed is None:
        return result
    if incoming["sequence"] < installed["sequence"]:
        result.update(status="BLOCK", action="DO_NOT_RUN", reason="downgrade_or_replayed_release")
    elif incoming["sequence"] == installed["sequence"] and incoming != installed:
        result.update(status="BLOCK", action="DO_NOT_RUN", reason="same_sequence_conflicting_manifest")
    elif any(incoming[k] != installed[k] for k in
             ("minecraft", "loader", "loader_version", "java_major")):
        result.update(status="REVIEW_REQUIRED", action="MIGRATION_TEST_REQUIRED",
                      reason="minecraft_loader_or_java_changed")
    elif any(incoming[k] != installed[k] for k in ("updater_contract", "sync_feed")):
        result.update(status="REVIEW_REQUIRED", action="INSTALLER_RECONFIG_REQUIRED",
                      reason="trusted_updater_endpoint_or_contract_changed")
    else:
        result.update(status="READY", action="RUN_EXISTING_UPDATER",
                      reason="compatible_existing_instance_requires_normal_mod_sync")
    return result


def evaluate(
    incoming_path: Path, incoming_signature: Path,
    pub_path: Path, installed_path: Path | None, installed_signature: Path | None,
    expected_profile: str, allowed_host: str
) -> dict:
    if not ID.fullmatch(expected_profile):
        raise ReleaseBlocked("invalid_expected_profile")
    if (installed_path is None) != (installed_signature is None):
        raise ReleaseBlocked("installed_signature_required")
    try:
        public_key = load_pem_public_key(_load_bytes(pub_path, MAX_PUBLIC_KEY_SIZE))
    except (TypeError, ValueError) as exc:
        raise ReleaseBlocked("invalid_pinned_key") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ReleaseBlocked("pinned_key_must_be_ed25519")
    incoming = _verify_release(incoming_path, incoming_signature, public_key,
                               expected_profile=expected_profile, allowed_host=allowed_host)
    installed = None
    if installed_path is not None:
        installed = _verify_release(installed_path, installed_signature, public_key,
                                    expected_profile=expected_profile, allowed_host=allowed_host)
    result = decide(installed, incoming)
    result.update(profile=expected_profile, current_sequence=installed["sequence"] if installed else None,
                  incoming_sequence=incoming["sequence"])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify signed release compatibility (no downloads, no writes)")
    parser.add_argument("--incoming", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--installed-signature", type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--allowed-host", required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.incoming, args.signature, args.public_key,
                          args.installed, args.installed_signature,
                          args.profile, args.allowed_host)
    except (ReleaseBlocked, OSError) as exc:
        print(json.dumps({"status": "BLOCK", "action": "DO_NOT_RUN",
                          "reason": str(exc)[:170], "write_performed": False,
                          "download_performed": False, "game_launched": False}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "READY" else 3


if __name__ == "__main__":
    sys.exit(main())
